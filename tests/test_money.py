import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.database import DatabaseManager
from core.money import parse_usd_to_minor


class MoneyCodecTests(unittest.TestCase):
    def test_parses_exact_usd_minor_units(self):
        self.assertEqual(parse_usd_to_minor("$120.34"), 12034)
        self.assertEqual(parse_usd_to_minor("-0.01"), -1)

    def test_rejects_fractional_cents_and_malformed_values(self):
        for value in ("1.001", "N/A", "", None, 12.34):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_usd_to_minor(value)


class SQLiteMoneyMigrationTests(unittest.TestCase):
    def test_existing_orders_are_null_only_backfilled_exactly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "orders.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE orders (
                    order_number TEXT PRIMARY KEY,
                    total_price TEXT
                );
                INSERT INTO orders (order_number, total_price)
                VALUES ('legacy', '$120.34');
                """
            )
            connection.commit()
            connection.close()

            manager = DatabaseManager(
                db_config={
                    "filename": str(db_path),
                    "tables": {
                        "orders": """
                            CREATE TABLE IF NOT EXISTS orders (
                                order_number TEXT PRIMARY KEY,
                                total_price TEXT,
                                total_price_minor INTEGER,
                                currency_code TEXT
                            )
                        """
                    },
                }
            )
            assert manager.connection is not None
            row = manager.connection.execute(
                """
                SELECT total_price, total_price_minor, currency_code
                FROM orders WHERE order_number = 'legacy'
                """
            ).fetchone()
            manager.close()

        self.assertEqual(row, ("$120.34", 12034, "USD"))

    def test_new_orders_write_canonical_money_without_overwriting_legacy_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "orders.sqlite3"
            manager = DatabaseManager(
                db_config={
                    "filename": str(db_path),
                    "tables": {
                        "orders": """
                            CREATE TABLE IF NOT EXISTS orders (
                                order_number TEXT PRIMARY KEY,
                                order_date TEXT,
                                total_price TEXT,
                                status TEXT,
                                email_address TEXT,
                                state TEXT,
                                website TEXT
                            )
                        """,
                        "products": """
                            CREATE TABLE IF NOT EXISTS products (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                title TEXT,
                                price TEXT,
                                quantity TEXT
                            )
                        """,
                        "tracking_numbers": """
                            CREATE TABLE IF NOT EXISTS tracking_numbers (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                tracking_number TEXT
                            )
                        """,
                    },
                }
            )
            manager.insert_order(
                {
                    "number": "new",
                    "date": "2026-08-26",
                    "total_price": "$120.34",
                    "status": "Shipped",
                    "email_address": "buyer@example.com",
                    "products": [],
                    "tracking": [],
                }
            )
            assert manager.connection is not None
            row = manager.connection.execute(
                """
                SELECT total_price, total_price_minor, currency_code
                FROM orders WHERE order_number = 'new'
                """
            ).fetchone()
            manager.close()

        self.assertEqual(row, ("$120.34", 12034, "USD"))

    def test_invalid_new_order_money_fails_before_order_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "orders.sqlite3"
            manager = DatabaseManager(
                db_config={
                    "filename": str(db_path),
                    "tables": {
                        "orders": """
                            CREATE TABLE IF NOT EXISTS orders (
                                order_number TEXT PRIMARY KEY,
                                order_date TEXT,
                                total_price TEXT,
                                status TEXT,
                                email_address TEXT,
                                state TEXT,
                                website TEXT
                            )
                        """,
                        "products": """
                            CREATE TABLE IF NOT EXISTS products (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                title TEXT,
                                price TEXT,
                                quantity TEXT
                            )
                        """,
                        "tracking_numbers": """
                            CREATE TABLE IF NOT EXISTS tracking_numbers (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                tracking_number TEXT
                            )
                        """,
                    },
                }
            )

            with self.assertRaisesRegex(ValueError, "fractional cent"):
                manager.insert_order(
                    {
                        "number": "invalid",
                        "date": "2026-08-26",
                        "total_price": "$1.005",
                        "status": "Shipped",
                        "email_address": "buyer@example.com",
                        "products": [],
                        "tracking": [],
                    }
                )

            assert manager.connection is not None
            self.assertIsNone(
                manager.connection.execute(
                    "SELECT 1 FROM orders WHERE order_number = 'invalid'"
                ).fetchone()
            )
            manager.close()

    def test_sqlite_cutover_gate_blocks_writes_across_processes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "orders.sqlite3"
            gate_path = root / "sqlite-write-gate"
            manager = DatabaseManager(
                db_config={
                    "filename": str(db_path),
                    "tables": {
                        "orders": """
                            CREATE TABLE IF NOT EXISTS orders (
                                order_number TEXT PRIMARY KEY,
                                order_date TEXT,
                                total_price TEXT,
                                status TEXT,
                                email_address TEXT,
                                state TEXT,
                                website TEXT
                            )
                        """,
                        "products": """
                            CREATE TABLE IF NOT EXISTS products (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                title TEXT,
                                price TEXT,
                                quantity TEXT
                            )
                        """,
                        "tracking_numbers": """
                            CREATE TABLE IF NOT EXISTS tracking_numbers (
                                id INTEGER PRIMARY KEY,
                                order_id TEXT,
                                tracking_number TEXT
                            )
                        """,
                    },
                }
            )
            gate_path.write_text("minor-money-v1\n")

            with patch.dict(
                "os.environ",
                {"IEIDLLC_MONEY_CUTOVER_GATE_FILE": str(gate_path)},
            ):
                with self.assertRaisesRegex(RuntimeError, "writes are paused"):
                    manager.insert_order(
                        {
                            "number": "paused",
                            "date": "2026-08-26",
                            "total_price": "$1.00",
                            "status": "Shipped",
                            "email_address": "buyer@example.com",
                            "products": [],
                            "tracking": [],
                        }
                    )

            assert manager.connection is not None
            self.assertIsNone(
                manager.connection.execute(
                    "SELECT 1 FROM orders WHERE order_number = 'paused'"
                ).fetchone()
            )
            manager.close()


if __name__ == "__main__":
    unittest.main()
