import json
import unittest

from typing_extensions import override

from api.submitter import OrderAPISubmitter
from core.scanned_order_writer import PostgresSettings, ScannedOrderWriter


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (1,)

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        return None


class ScannedOrderWriterTests(unittest.TestCase):
    @override
    def setUp(self):
        self.connection = FakeConnection()
        self.settings = PostgresSettings(
            host="db",
            port=5432,
            database="postgres",
            user="postgres",
            password="secret",
            owner_id="a0000000-0000-4000-8000-000000000001",
        )
        self.writer = ScannedOrderWriter(
            settings=self.settings,
            connect=lambda **_kwargs: self.connection,
        )

    def test_upserts_exact_minor_units_with_partial_index_predicate(self):
        order = {
            "number": "BB-12034",
            "date": "2026-08-26",
            "total_price": "$120.34",
            "tracking": ["1Z9999999999999999"],
            "website": "BestBuy",
            "products": [{"title": "Console", "quantity": "1"}],
        }

        result = self.writer.write_order(order)

        self.assertTrue(result["success"])
        sql, params = self.connection.cursor_instance.calls[-1]
        self.assertIn(
            "ON CONFLICT (user_id, provider, source_key)",
            " ".join(sql.split()),
        )
        self.assertIn(
            "WHERE source_key IS NOT NULL AND btrim(source_key) <> ''",
            " ".join(sql.split()),
        )
        self.assertEqual(params[0], self.settings.owner_id)
        self.assertEqual(params[1], "bbos")
        self.assertEqual(params[2], "BB-12034_1Z9999999999999999")
        self.assertEqual(params[3], "1Z9999999999999999")
        self.assertEqual(params[4], 12034)
        self.assertEqual(params[5], "USD")
        self.assertEqual(json.loads(params[6]), order)
        self.assertEqual(self.connection.commits, 1)

    def test_writes_each_distinct_tracking_number_with_its_own_source_key(self):
        order = {
            "number": "BB-MULTI",
            "date": "2026-08-26",
            "total_price": "$12.34",
            "tracking": ["1Z-FIRST", "1Z-SECOND", "1Z-FIRST", ""],
        }

        result = self.writer.write_order(order)

        self.assertTrue(result["success"])
        self.assertEqual(result["submitted"], 2)
        self.assertEqual(result["tracking_numbers"], ["1Z-FIRST", "1Z-SECOND"])
        self.assertEqual(result["tracking_number"], "1Z-FIRST")
        writes = self.connection.cursor_instance.calls
        self.assertEqual(
            [params[2] for _sql, params in writes],
            [
                "BB-MULTI_1Z-FIRST",
                "BB-MULTI_1Z-SECOND",
            ],
        )
        self.assertEqual(
            [params[3] for _sql, params in writes],
            [
                "1Z-FIRST",
                "1Z-SECOND",
            ],
        )
        self.assertEqual(self.connection.commits, 1)

    def test_rejects_missing_required_order_fields_without_connecting(self):
        for order in (
            {"number": "BB-1", "total_price": "$1.00", "tracking": []},
            {"total_price": "$1.00", "tracking": ["1Z"]},
            {"number": "BB-1", "total_price": "N/A", "tracking": ["1Z"]},
        ):
            with self.subTest(order=order):
                result = self.writer.write_order(order)
                self.assertFalse(result["success"])
        self.assertEqual(self.connection.cursor_instance.calls, [])

    def test_environment_settings_fail_closed_when_incomplete(self):
        with self.assertRaises(ValueError, msg="missing PostgreSQL settings"):
            PostgresSettings.from_env({})


class FakeWriter:
    def __init__(self):
        self.orders = []

    def health(self):
        return {
            "success": True,
            "status": "healthy",
            "database": "connected",
            "message": "PostgreSQL is healthy",
        }

    def write_order(self, order):
        self.orders.append(order)
        return {
            "success": True,
            "message": "stored",
            "submitted": 1,
            "tracking_number": order["tracking"][0],
        }


class DirectSubmitterTests(unittest.TestCase):
    def test_single_and_bulk_submission_use_direct_writer(self):
        writer = FakeWriter()
        submitter = OrderAPISubmitter(writer=writer)
        first = {
            "number": "one",
            "tracking": ["1Z", "1Z-extra"],
            "total_price": "$1.00",
        }
        second = {"number": "two", "tracking": ["2Z"], "total_price": "$2.00"}

        self.assertTrue(submitter.check_api_health()["success"])
        self.assertTrue(submitter.submit_order(first)["success"])
        bulk = submitter.submit_orders_bulk([second])

        self.assertTrue(bulk["success"])
        self.assertEqual(bulk["total_submitted"], 1)
        self.assertEqual(bulk["order_results"][0]["result"]["tracking_number"], "2Z")
        self.assertEqual(writer.orders, [first, second])


if __name__ == "__main__":
    unittest.main()
