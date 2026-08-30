import unittest
from unittest.mock import Mock

from continuous_monitor import ContinuousMonitor


class ContinuousMonitorTests(unittest.TestCase):
    def test_records_every_tracking_number_successfully_written(self):
        monitor = ContinuousMonitor.__new__(ContinuousMonitor)
        monitor.api_config = Mock()
        monitor.api_config.is_enabled.return_value = True
        database = Mock()
        database.get_orders_with_tracking_since_date.return_value = [
            {
                "number": "BB-MULTI",
                "tracking": ["1Z-FIRST", "1Z-SECOND"],
            }
        ]
        database.is_tracking_key_submitted.return_value = False
        monitor.output_handler = Mock(db_manager=database)
        monitor.api_submitter = Mock()
        monitor.api_submitter.submit_orders_bulk.return_value = {
            "success": True,
            "message": "Stored 2 scanned orders",
            "total_submitted": 2,
            "total_failed": 0,
            "order_results": [
                {
                    "order_number": "BB-MULTI",
                    "result": {
                        "success": True,
                        "submitted": 2,
                        "tracking_numbers": ["1Z-FIRST", "1Z-SECOND"],
                    },
                }
            ],
        }
        monitor.submitted_tracking_keys = set()

        monitor.submit_recent_trackings(lookback_days=0)

        database.add_submitted_tracking_keys_batch.assert_called_once_with(
            [
                {
                    "tracking_key": "BB-MULTI_1Z-FIRST",
                    "order_number": "BB-MULTI",
                    "tracking_number": "1Z-FIRST",
                },
                {
                    "tracking_key": "BB-MULTI_1Z-SECOND",
                    "order_number": "BB-MULTI",
                    "tracking_number": "1Z-SECOND",
                },
            ]
        )
        self.assertEqual(
            monitor.submitted_tracking_keys,
            {"BB-MULTI_1Z-FIRST", "BB-MULTI_1Z-SECOND"},
        )


if __name__ == "__main__":
    unittest.main()
