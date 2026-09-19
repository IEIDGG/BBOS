from pathlib import Path

from email_processing.handlers import AppleEmailHandler


FIXTURES = Path(__file__).parent / "fixtures"


def load_email_data(name: str) -> tuple[bytes, bytes]:
    return (b"fixture-" + name.encode(), (FIXTURES / name).read_bytes())


class FakeConnector:
    def __init__(self, messages: dict[str, tuple[bytes, bytes]]):
        self.messages = messages
        self.searches = []
        self.processed_uids = []

    def search_emails(self, folder, criteria, use_uid_filter=True):
        self.searches.append((folder, criteria, use_uid_filter))
        return True, list(self.messages)

    def fetch_email(self, message_id, use_uid=True):
        return True, self.messages[message_id]

    def fetch_emails_batch(self, message_ids, use_uid=True):
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
