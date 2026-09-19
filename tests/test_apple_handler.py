import inspect
from pathlib import Path

from email_processing.handlers import AppleEmailHandler


FIXTURES = Path(__file__).parent / "fixtures"


def load_email_data(name: str) -> tuple[bytes, bytes]:
    return (b"fixture-" + name.encode(), (FIXTURES / name).read_bytes())


class FakeConnector:
    def __init__(
        self,
        messages: dict[str, tuple[bytes, bytes]],
        fetch_overrides=None,
        batch_results=None,
    ):
        self.messages = messages
        self.fetch_overrides = fetch_overrides or {}
        self.batch_results = batch_results
        self.searches = []
        self.processed_uids = []

    def search_emails(self, folder, criteria, use_uid_filter=True):
        self.searches.append((folder, criteria, use_uid_filter))
        return True, list(self.messages)

    def fetch_email(self, message_id, use_uid=True):
        if message_id in self.fetch_overrides:
            return self.fetch_overrides[message_id]
        return True, self.messages[message_id]

    def fetch_emails_batch(self, message_ids, use_uid=True):
        if self.batch_results is not None:
            return self.batch_results
        return [self.messages[message_id] for message_id in message_ids]

    def mark_uid_processed(self, uid):
        self.processed_uids.append(uid)


def test_confirmation_uses_apple_criteria_and_returns_processing_order():
    connector = FakeConnector({"confirm": load_email_data("apple_confirmation.eml")})

    orders = AppleEmailHandler(connector).process_confirmation_emails(
        "INBOX", date_filter="2026/09/01"
    )

    assert orders == [
        {
            "date": "2026-09-12",
            "number": "W9999999999",
            "status": "Processing",
            "tracking": [],
            "products": [
                {
                    "title": "iPhone 18 Pro Max 256GB Burgundy",
                    "quantity": "1",
                    "price": "$1,299.00",
                }
            ],
            "total_price": "$1,299.00",
            "email_address": "buyer@example.test",
            "order_details_link": "https://secure.example.test/vieworder/W9999999999/buyer@example.test/",
            "shipping_city": "Concord",
            "state": "NH",
            "zip": "03301",
            "zip_and_state": "Concord, NH 03301",
            "estimated_delivery": "Sep 29 – Oct 6",
            "website": "Apple",
        }
    ]
    assert connector.searches == [
        (
            "INBOX",
            {
                "from": '(OR (FROM "orders.apple.com") (FROM "email.apple.com"))',
                "subject": "(OR (SUBJECT \"We're processing your order\") (SUBJECT \"We’re processing your order\") (SUBJECT \"Thank you for your order\"))",
                "date": "after:2026/09/01",
            },
            True,
        )
    ]
    assert connector.processed_uids == ["confirm"]


def test_cancellation_appends_minimal_unknown_order():
    connector = FakeConnector({"cancel": load_email_data("apple_cancellation.eml")})
    orders = []

    AppleEmailHandler(connector).process_cancellation_emails(
        "INBOX", orders, date_filter="2026/06/01"
    )

    assert orders == [
        {
            "date": "2026-04-23",
            "number": "W9999999998",
            "status": "Cancelled",
            "tracking": [],
            "products": [],
            "website": "Apple",
            "email_address": "buyer@example.test",
        }
    ]
    assert connector.searches[0][1]["date"] == "after:2026/06/01"
    assert connector.processed_uids == ["cancel"]


def test_shipment_merges_unique_tracking_and_preserves_cancelled_status():
    connector = FakeConnector({"ship": load_email_data("apple_shipment.eml")})
    orders = [
        {
            "number": "W9999999997",
            "status": "Cancelled",
            "tracking": ["1Z999AA10123456784"],
        }
    ]

    AppleEmailHandler(connector).process_shipped_emails("INBOX", orders)

    assert orders[0]["status"] == "Cancelled"
    assert orders[0]["tracking"] == ["1Z999AA10123456784"]
    assert orders[0]["products"] == [
        {
            "title": "iPhone 18 Pro Max 256GB Black",
            "quantity": "1",
            "price": "$1,299.00",
        }
    ]
    assert orders[0]["state"] == "NH"
    assert orders[0]["zip"] == "03301"
    assert orders[0]["estimated_delivery"] == "Sep 24, 2026"
    assert orders[0]["website"] == "Apple"
    assert connector.processed_uids == ["ship"]


def test_shipment_creates_order_only_when_tracking_exists():
    connector = FakeConnector({"ship": load_email_data("apple_shipment.eml")})
    orders = []

    AppleEmailHandler(connector).process_shipped_emails("INBOX", orders)

    assert orders == [
        {
            "date": "2026-09-12",
            "number": "W9999999997",
            "status": "Shipped",
            "tracking": ["1Z999AA10123456784"],
            "products": [
                {
                    "title": "iPhone 18 Pro Max 256GB Black",
                    "quantity": "1",
                    "price": "$1,299.00",
                }
            ],
            "total_price": "",
            "email_address": "buyer@example.test",
            "order_details_link": "",
            "shipping_city": "Concord",
            "state": "NH",
            "zip": "03301",
            "zip_and_state": "Concord, NH 03301",
            "estimated_delivery": "Sep 24, 2026",
            "carrier": "UPS",
            "website": "Apple",
        }
    ]
    assert connector.processed_uids == ["ship"]


def test_malformed_candidate_is_skipped_and_other_uid_is_processed():
    connector = FakeConnector(
        {
            "bad": (b"fixture-bad", b"not a MIME email"),
            "good": load_email_data("apple_confirmation.eml"),
        }
    )

    handler = AppleEmailHandler(connector)
    orders = handler.process_confirmation_emails("INBOX")

    assert [order["number"] for order in orders] == ["W9999999999"]
    assert connector.processed_uids == ["good"]
    assert handler.statistics["processed"] == 2
    assert handler.statistics["successful"] == 1
    assert handler.statistics["failed"] == 1


def test_cancellation_keeps_order_handler_payment_declined_signature():
    parameter = inspect.signature(
        AppleEmailHandler.process_cancellation_emails
    ).parameters["mark_payment_declined_as_cancelled"]

    assert parameter.default is True


def test_duplicate_tracking_values_from_one_result_are_stored_once():
    connector = FakeConnector({"ship": load_email_data("apple_shipment.eml")})
    handler = AppleEmailHandler(connector)
    process_shipment = handler.processor.process_apple_shipped_email

    def process_duplicate_shipment(email_data):
        result = process_shipment(email_data)
        result["tracking_numbers"] += [result["tracking_numbers"][0]]
        return result

    handler.processor.process_apple_shipped_email = process_duplicate_shipment
    orders = []

    handler.process_shipped_emails("INBOX", orders)

    assert orders[0]["tracking"] == ["1Z999AA10123456784"]


def test_failed_and_empty_fetch_candidates_count_as_processed_failures():
    messages = {
        "failed": load_email_data("apple_confirmation.eml"),
        "empty": load_email_data("apple_confirmation.eml"),
        "good": load_email_data("apple_confirmation.eml"),
    }
    connector = FakeConnector(
        messages,
        fetch_overrides={"failed": (False, None), "empty": (True, None)},
    )
    handler = AppleEmailHandler(connector)

    orders = handler.process_confirmation_emails("INBOX")

    assert [order["number"] for order in orders] == ["W9999999999"]
    assert connector.processed_uids == ["good"]
    assert handler.statistics["processed"] == 3
    assert handler.statistics["successful"] == 1
    assert handler.statistics["failed"] == 2


def test_batch_candidates_keep_uid_association_and_count_empty_slot():
    messages = {
        f"uid-{index}": load_email_data("apple_confirmation.eml")
        for index in range(11)
    }
    batch_results = [
        None if message_id == "uid-5" else messages[message_id]
        for message_id in messages
    ]
    connector = FakeConnector(messages, batch_results=batch_results)
    handler = AppleEmailHandler(connector)

    orders = handler.process_confirmation_emails("INBOX")

    assert len(orders) == 10
    assert connector.processed_uids == [
        f"uid-{index}" for index in range(11) if index != 5
    ]
    assert handler.statistics["processed"] == 11
    assert handler.statistics["failed"] == 1
