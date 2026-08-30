import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.database import DatabaseManager
from core.money import (
    MoneyIntegrityError,
    MoneyUnavailableError,
    display_order_total,
    parse_usd_to_minor,
    resolve_usd_money,
)


class MoneyCodecTests(unittest.TestCase):
    def test_parses_exact_usd_minor_units(self):
        self.assertEqual(parse_usd_to_minor("$120.34"), 12034)
        self.assertEqual(parse_usd_to_minor("-0.01"), -1)

    def test_rejects_fractional_cents_and_malformed_values(self):
        for value in ("1.001", "N/A", "", None, 12.34):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_usd_to_minor(value)

    def test_resolves_and_formats_every_valid_cutover_generation(self):
        rows = (
            ({"total_price": "$120.34"}, "legacy"),
            (
                {"total_price_minor": 12034, "currency_code": "USD"},
                "canonical",
            ),
            (
                {
                    "total_price": "$120.34",
                    "total_price_minor": 12034,
                    "currency_code": "USD",
                },
                "canonical",
            ),
        )
        for row, source in rows:
            with self.subTest(row=row):
                self.assertEqual(resolve_usd_money(row).source, source)
                self.assertEqual(display_order_total(row), "$120.34")

    def test_preserves_zero_and_negative_minor_units(self):
        for amount_minor, display in ((0, "$0.00"), (-1, "$-0.01")):
            with self.subTest(amount_minor=amount_minor):
                self.assertEqual(
                    display_order_total(
                        {
                            "total_price_minor": amount_minor,
                            "currency_code": "USD",
                        }
                    ),
                    display,
                )

    def test_rejects_missing_incomplete_conflicting_and_non_usd_money(self):
        unsafe = (
            {},
            {"total_price_minor": 100},
            {"currency_code": "USD"},
            {"total_price_minor": True, "currency_code": "USD"},
            {"total_price_minor": 100, "currency_code": "CAD"},
            {"total_price": "N/A"},
            {
                "total_price": "$1.01",
                "total_price_minor": 100,
                "currency_code": "USD",
            },
        )
        for row in unsafe:
            with (
                self.subTest(row=row),
                self.assertRaises((MoneyUnavailableError, MoneyIntegrityError)),
            ):
                resolve_usd_money(row)


class SQLiteMoneyMigrationTests(unittest.TestCase):
    def _manager(self, db_path: Path) -> DatabaseManager:
        return DatabaseManager(
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

    def _insert_valid_order(self, manager: DatabaseManager) -> None:
        manager.insert_order(
            {
                "number": "lifecycle",
                "date": "2026-08-30",
                "total_price": "$120.34",
                "status": "Shipped",
                "email_address": "buyer@example.com",
                "products": [],
                "tracking": [],
            }
        )

    def test_order_readers_display_legacy_mixed_and_canonical_only_identically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir) / "orders.sqlite3")
            self._insert_valid_order(manager)
            assert manager.connection is not None

            states = (
                ("$120.34", None, None),
                ("$120.34", 12034, "USD"),
                (None, 12034, "USD"),
            )
            for total_price, amount_minor, currency_code in states:
                with self.subTest(state=(total_price, amount_minor, currency_code)):
                    manager.connection.execute(
                        "UPDATE orders SET total_price = ?, total_price_minor = ?, "
                        "currency_code = ? WHERE order_number = 'lifecycle'",
                        (total_price, amount_minor, currency_code),
                    )
                    manager.connection.commit()
                    row = manager.get_order_by_number("lifecycle")
                    self.assertIsNotNone(row)
                    self.assertEqual(row["total_price"], "$120.34")
                    self.assertEqual(row["total_price_minor"], 12034)
                    self.assertEqual(row["currency_code"], "USD")
                    self.assertEqual(
                        manager.get_all_orders()[0]["total_price"], "$120.34"
                    )
            manager.close()

    def test_order_readers_fail_closed_on_conflicting_money(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir) / "orders.sqlite3")
            self._insert_valid_order(manager)
            assert manager.connection is not None
            manager.connection.execute(
                "UPDATE orders SET total_price = '$120.35' "
                "WHERE order_number = 'lifecycle'"
            )
            manager.connection.commit()

            self.assertIsNone(manager.get_order_by_number("lifecycle"))
            self.assertEqual(manager.get_all_orders(), [])
            manager.close()

    def test_successful_orders_snapshot_formats_canonical_only_money(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir) / "orders.sqlite3")
            self._insert_valid_order(manager)
            assert manager.connection is not None
            manager.connection.execute(
                "UPDATE orders SET total_price = NULL WHERE order_number = 'lifecycle'"
            )
            manager.connection.commit()
            manager.create_successful_orders_view()
            row = manager.connection.execute(
                "SELECT total_price, total_price_minor, currency_code "
                "FROM successful_orders WHERE order_number = 'lifecycle'"
            ).fetchone()
            manager.close()

        self.assertEqual(row, ("$120.34", 12034, "USD"))

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

    def test_closed_gate_allows_legacy_reads_without_schema_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "orders.sqlite3"
            gate_path = root / "sqlite-write-gate"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE orders (
                    order_number TEXT PRIMARY KEY,
                    order_date TEXT,
                    total_price TEXT,
                    status TEXT,
                    email_address TEXT,
                    state TEXT
                );
                CREATE TABLE products (
                    order_id TEXT, title TEXT, price TEXT, quantity TEXT
                );
                CREATE TABLE tracking_numbers (
                    order_id TEXT, tracking_number TEXT
                );
                INSERT INTO orders VALUES (
                    'legacy', '2026-08-30', '$12.34', 'Shipped',
                    'buyer@example.com', 'NY'
                );
                """
            )
            connection.commit()
            connection.close()
            gate_path.write_text("minor-money-v1\n")

            with patch.dict(
                "os.environ",
                {"IEIDLLC_MONEY_CUTOVER_GATE_FILE": str(gate_path)},
            ):
                manager = self._manager(db_path)
                row = manager.get_order_by_number("legacy")
                self.assertEqual(row["total_price"], "$12.34")
                self.assertEqual(row["total_price_minor"], 1234)
                assert manager.connection is not None
                columns = {
                    item[1]
                    for item in manager.connection.execute(
                        "PRAGMA table_info(orders)"
                    ).fetchall()
                }
                self.assertNotIn("total_price_minor", columns)
                with self.assertRaisesRegex(RuntimeError, "writes are paused"):
                    manager.insert_order(
                        {
                            "number": "blocked",
                            "date": "2026-08-30",
                            "total_price": "$1.00",
                            "status": "Shipped",
                            "email_address": "buyer@example.com",
                            "products": [],
                            "tracking": [],
                        }
                    )
                manager.close()

    def test_invalid_legacy_money_fails_database_initialization_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "orders.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE orders (order_number TEXT PRIMARY KEY, total_price TEXT)"
            )
            connection.execute("INSERT INTO orders VALUES ('bad', 'N/A')")
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(ValueError, "cannot migrate"):
                DatabaseManager(
                    db_config={
                        "filename": str(db_path),
                        "tables": {
                            "orders": """
                                CREATE TABLE IF NOT EXISTS orders (
                                    order_number TEXT PRIMARY KEY,
                                    total_price TEXT
                                )
                            """
                        },
                    }
                )


if __name__ == "__main__":
    unittest.main()
