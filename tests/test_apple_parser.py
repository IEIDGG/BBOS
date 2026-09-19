import base64
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from config.settings import APPLE_SEARCH_CRITERIA
from email_processing.connector import EmailConnector
from email_processing.parsers.apple_parser import AppleParser
from email_processing.processor import EmailProcessor

FIXTURES = Path(__file__).parent / "fixtures"


def load_html(name: str) -> tuple[str, str, str]:
    message = BytesParser(policy=policy.default).parsebytes(
        (FIXTURES / name).read_bytes()
    )
    html_part = next(
        part for part in message.walk() if part.get_content_type() == "text/html"
    )
    html = html_part.get_content().replace(
        "https://secure.example.test", "https://store.apple.com"
    )
    return html, message["Subject"], message["To"]


def load_email_data(name: str) -> tuple[bytes, bytes]:
    return (b"fixture-" + name.encode(), (FIXTURES / name).read_bytes())


def link_only_email(subject: str, marker: str, href: str) -> tuple[bytes, bytes]:
    raw = f"""From: Apple <orders@apple.example.test>
To: buyer@example.test
Date: Sat, 19 Sep 2026 12:00:00 +0000
Subject: {subject}
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

<html><body><p>{marker}</p><a href="{href}">View order</a></body></html>
"""
    return b"link-only", raw.encode()


def test_apple_search_criteria_cover_all_email_types():
    assert set(APPLE_SEARCH_CRITERIA) == {"confirmation", "cancellation", "shipped"}
    assert "orders.apple.com" in APPLE_SEARCH_CRITERIA["confirmation"]["from"]
    assert APPLE_SEARCH_CRITERIA["confirmation"]["subject"] == (
        '(OR (SUBJECT "processing your order") (SUBJECT "Thank you for your order"))'
    )
    assert "Your shipment is on its way" in APPLE_SEARCH_CRITERIA["shipped"]["subject"]


class DecodedSubjectSearchConnection:
    def __init__(self, messages: dict[bytes, bytes]):
        self.messages = messages
        self.criteria = []

    def select(self, folder):
        return "OK", [b""]

    def uid(self, command, *args):
        assert command == "search"
        criteria = args[-1].decode("ascii")
        self.criteria.append(criteria)
        subjects = re.findall(r'SUBJECT "([^"]+)"', criteria)
        matches = []
        for uid, raw_message in self.messages.items():
            subject = BytesParser(policy=policy.default).parsebytes(raw_message)[
                "Subject"
            ]
            if any(needle.casefold() in str(subject).casefold() for needle in subjects):
                matches.append(uid)
        return "OK", [b" ".join(matches)]


def test_real_connector_finds_decoded_straight_and_curly_confirmation_subjects():
    curly = base64.b64encode(
        "We’re processing your order W9999999999".encode("utf-8")
    ).decode("ascii")
    connection = DecodedSubjectSearchConnection(
        {
            b"11": b"Subject: =?utf-8?q?We're_processing_your_order_W9999999999?=\r\n\r\n",
            b"12": (f"Subject: =?utf-8?b?{curly}?=\r\n\r\n".encode("ascii")),
        }
    )
    connector = EmailConnector("buyer@example.test", "unused", "gmail")
    connector.connection = connection
    connector.processed_uids.clear()

    found, uids = connector.search_emails(
        "INBOX", APPLE_SEARCH_CRITERIA["confirmation"]
    )

    assert found is True
    assert uids == [b"11", b"12"]
    assert len(connection.criteria) == 1
    assert 'SUBJECT "processing your order"' in connection.criteria[0]
    assert "Were processing your order" not in connection.criteria[0]


def test_processor_delegates_apple_confirmation_fixture():
    result = EmailProcessor().process_apple_confirmation_email(
        load_email_data("apple_confirmation.eml")
    )

    assert result["order_number"] == "W9999999999"
    assert result["products"][0]["title"] == "iPhone 18 Pro Max 256GB Burgundy"
    assert result["email_address"] == "buyer@example.test"


def test_processor_delegates_apple_cancellation_fixture():
    result = EmailProcessor().process_apple_cancellation_email(
        load_email_data("apple_cancellation.eml")
    )

    assert result["order_number"] == "W9999999998"
    assert result["cancellation_type"] == "cancelled"
    assert result["email_address"] == "buyer@example.test"


def test_processor_delegates_apple_shipment_fixture():
    result = EmailProcessor().process_apple_shipped_email(
        load_email_data("apple_shipment.eml")
    )

    assert result["order_number"] == "W9999999997"
    assert result["tracking_numbers"] == ["1Z999AA10123456784"]
    assert result["carrier"] == "UPS"


def test_confirmation_extracts_catalog_fulfillment_and_order_link():
    html, subject, recipient = load_html("apple_confirmation.eml")
    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-12"
    )

    assert result["order_number"] == "W9999999999"
    assert result["date"] == "2026-09-12"
    assert result["products"] == [
        {
            "title": "iPhone 18 Pro Max 256GB Burgundy",
            "quantity": "1",
            "price": "$1,299.00",
        }
    ]
    assert result["total_price"] == "$1,299.00"
    assert result["estimated_delivery"] == "Sep 29 – Oct 6"
    assert result["state"] == "NH"
    assert result["zip"] == "03301"
    assert result["shipping_city"] == "Concord"
    assert result["email_address"] == "buyer@example.test"
    assert result["order_details_link"].endswith(
        "/vieworder/W9999999999/buyer@example.test/"
    )


def test_cancellation_requires_cancelled_body_and_keeps_catalog_optional():
    html, subject, recipient = load_html("apple_cancellation.eml")
    result = AppleParser().parse_cancellation(
        html, subject=subject, email_address=recipient, email_date="2026-06-15"
    )

    assert result["order_number"] == "W9999999998"
    assert result["date"] == "2026-04-23"
    assert result["cancellation_type"] == "cancelled"
    assert result["products"] == []
    assert result["order_details_link"] == ""


def test_shipment_extracts_tracking_and_location():
    html, subject, recipient = load_html("apple_shipment.eml")
    result = AppleParser().parse_shipment(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["order_number"] == "W9999999997"
    assert result["products"][0]["title"] == "iPhone 18 Pro Max 256GB Black"
    assert result["tracking_numbers"] == ["1Z999AA10123456784"]
    assert result["carrier"] == "UPS"
    assert result["estimated_delivery"] == "Sep 24, 2026"
    assert result["state"] == "NH"
    assert result["zip"] == "03301"


def test_curly_confirmation_subject_is_accepted():
    html, _, recipient = load_html("apple_confirmation.eml")
    result = AppleParser().parse_confirmation(
        html,
        subject="We’re processing your order W9999999999",
        email_address=recipient,
        email_date="2026-09-12",
    )
    assert result["order_number"] == "W9999999999"


def test_information_subject_without_cancelled_body_is_rejected():
    html, _, recipient = load_html("apple_cancellation.eml")
    html = html.replace("Your order has been cancelled", "Information about your order")
    result = AppleParser().parse_cancellation(
        html,
        subject="Information about your order W9999999998",
        email_address=recipient,
        email_date="2026-06-15",
    )
    assert result == {}


def test_shipment_without_tracking_value_returns_empty_tracking_numbers():
    html, subject, recipient = load_html("apple_shipment.eml")
    html = html.replace(
        '<td><a href="https://www.ups.example.test/track/1Z999AA10123456784">1Z999AA10123456784</a></td>',
        "<td></td>",
    )

    result = AppleParser().parse_shipment(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["tracking_numbers"] == []


def test_confirmation_keeps_single_date_delivery():
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace("Sep 29 – Oct 6", "Oct 6, 2026")

    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-12"
    )

    assert result["estimated_delivery"] == "Oct 6, 2026"


def test_confirmation_excludes_footer_qty_rows_from_products():
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace(
        "</body>",
        """
        <table class="footer-widget">
          <tr><td>Promotional Widget</td><td>$9.99</td></tr>
          <tr><td>Qty</td><td>1</td></tr>
        </table>
        </body>
        """,
    )

    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-12"
    )

    assert result["products"] == [
        {
            "title": "iPhone 18 Pro Max 256GB Burgundy",
            "quantity": "1",
            "price": "$1,299.00",
        }
    ]


@pytest.mark.parametrize(
    "kind,subject,marker,item_class",
    [
        (
            "confirmation",
            "Thank you for your order W9999999999",
            "Thank you for your order",
            "item-content",
        ),
        (
            "shipment",
            "Your shipment is on its way W9999999997",
            "Your shipment is on its way",
            "shipment-content",
        ),
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_products_ignore_flat_and_wrapped_footer_qty_rows(
    kind, subject, marker, item_class, wrapped
):
    item = f"""
      <table class="{item_class}"><tr><td>Actual Product</td><td>$10.00</td></tr>
        <tr><td>Qty</td><td>2</td></tr></table>
    """
    footer = """
      <table class="footer-widget"><tr><td>Promotional Widget</td><td>$9.99</td></tr>
        <tr><td>Qty</td><td>1</td></tr></table>
    """
    body = f"{item}{footer}"
    if wrapped:
        body = f'<table class="shipment-items"><tr><td>{body}</td></tr></table>'
    assert body.count("Actual Product") == 1
    assert body.count("Promotional Widget") == 1

    result = getattr(AppleParser(), f"parse_{kind}")(
        f"<p>{marker}</p>{body}",
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result["products"] == [
        {"title": "Actual Product", "quantity": "2", "price": "$10.00"}
    ]


@pytest.mark.parametrize(
    "kind,subject,marker,item_class",
    [
        (
            "confirmation",
            "Thank you for your order W9999999999",
            "Thank you for your order",
            "item-content",
        ),
        (
            "shipment",
            "Your shipment is on its way W9999999997",
            "Your shipment is on its way",
            "shipment-content",
        ),
    ],
)
@pytest.mark.parametrize("non_item_class", ["promotional-widget", "order-summary"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_products_ignore_nested_non_item_qty_rows(
    kind, subject, marker, item_class, non_item_class, wrapped
):
    item = f"""
      <table class="{item_class}"><tr><td>Actual Product</td><td>$10.00</td></tr>
        <tr><td>Qty</td><td>2</td></tr></table>
    """
    non_item = f"""
      <table class="{non_item_class}"><tr><td>Promotional Widget</td><td>$9.99</td></tr>
        <tr><td>Qty</td><td>1</td></tr></table>
    """
    body = f"{item}{non_item}"
    if wrapped:
        body = f'<table class="shipment-items"><tr><td>{body}</td></tr></table>'
    assert body.count("Actual Product") == 1
    assert body.count("Promotional Widget") == 1

    result = getattr(AppleParser(), f"parse_{kind}")(
        f"<p>{marker}</p>{body}",
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result["products"] == [
        {"title": "Actual Product", "quantity": "2", "price": "$10.00"}
    ]


@pytest.mark.parametrize(
    "kind,subject,marker,section_class",
    [
        (
            "confirmation",
            "Thank you for your order W9999999999",
            "Thank you for your order",
            "item-content",
        ),
        (
            "shipment",
            "Your shipment is on its way W9999999997",
            "Your shipment is on its way",
            "shipment-items",
        ),
    ],
)
@pytest.mark.parametrize("line_count", [1, 2])
def test_products_keep_classless_nested_layout_lines(
    kind, subject, marker, section_class, line_count
):
    line = """
      <table><tr><td>Actual Product</td><td>$10.00</td></tr>
        <tr><td>Qty</td><td>2</td></tr></table>
    """
    nested_lines = line * line_count
    html = (
        f'<p>{marker}</p><table class="{section_class}"><tr><td>'
        f"{nested_lines}</td></tr></table>"
    )
    assert html.count("Actual Product") == line_count
    assert html.count('class="item-content"') == (1 if kind == "confirmation" else 0)

    result = getattr(AppleParser(), f"parse_{kind}")(
        html,
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert (
        result["products"]
        == [{"title": "Actual Product", "quantity": "2", "price": "$10.00"}]
        * line_count
    )


@pytest.mark.parametrize(
    "kind,subject,wrapper_class,item_class",
    [
        (
            "confirmation",
            "Thank you for your order W9999999999",
            "shipment-items",
            "item-content",
        ),
        (
            "shipment",
            "Your shipment is on its way W9999999997",
            "item-wrapper",
            "shipment-content",
        ),
    ],
)
def test_nested_eligible_item_wrapper_processes_each_physical_line_once(
    kind, subject, wrapper_class, item_class
):
    lines = """
      <table class="item-content"><tr><td>Widget A</td><td>$10.00</td></tr>
        <tr><td>Qty</td><td>1</td></tr></table>
      <table class="item-content"><tr><td>Widget B</td><td>$20.00</td></tr>
        <tr><td>Qty</td><td>2</td></tr></table>
    """.replace('class="item-content"', f'class="{item_class}"')
    html = f"""
      <p>{subject.rsplit(" W", 1)[0]}</p>
      <table class="{wrapper_class}"><tr><td>{lines}</td></tr></table>
    """

    result = getattr(AppleParser(), f"parse_{kind}")(
        html,
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result["products"] == [
        {"title": "Widget A", "quantity": "1", "price": "$10.00"},
        {"title": "Widget B", "quantity": "2", "price": "$20.00"},
    ]


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_eligible_item_wrapper_keeps_identical_lines_distinct(kind):
    subject = (
        "Thank you for your order W9999999999"
        if kind == "confirmation"
        else "Your shipment is on its way W9999999997"
    )
    html = f"""
      <p>{subject.rsplit(" W", 1)[0]}</p>
      <table class="shipment-items"><tr><td>
        <table class="item-content"><tr><td>Same Widget</td><td>$10.00</td></tr>
          <tr><td>Qty</td><td>1</td></tr></table>
        <table class="item-content"><tr><td>Same Widget</td><td>$10.00</td></tr>
          <tr><td>Qty</td><td>1</td></tr></table>
      </td></tr></table>
    """

    result = getattr(AppleParser(), f"parse_{kind}")(
        html,
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result["products"] == [
        {"title": "Same Widget", "quantity": "1", "price": "$10.00"},
        {"title": "Same Widget", "quantity": "1", "price": "$10.00"},
    ]


def test_confirmation_without_address_or_footer_has_empty_location_fields():
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace(
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>", ""
    ).replace(
        '<a href="https://store.apple.com/vieworder/W9999999999/buyer@example.test/">View order</a>',
        "",
    )

    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-12"
    )

    assert result["shipping_city"] == ""
    assert result["state"] == ""
    assert result["zip"] == ""
    assert result["order_details_link"] == ""


@pytest.mark.parametrize(
    "subject",
    [
        "We're processing your order W9999999999",
        "We’re processing your order W9999999999",
        "THANK YOU FOR YOUR ORDER W9999999999",
    ],
)
def test_confirmation_accepts_supported_subjects_with_order_content(subject):
    html, _, recipient = load_html("apple_confirmation.eml")
    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )
    assert result["order_number"] == "W9999999999"
    assert result["products"][0]["quantity"] == "1"


@pytest.mark.parametrize(
    "method,subject",
    [
        ("parse_confirmation", "We're processing your order W9999999999"),
        ("parse_confirmation", "We’re processing your order W9999999999"),
        ("parse_confirmation", "Thank you for your order W9999999999"),
        ("parse_shipment", "Your shipment is on its way W9999999999"),
    ],
)
@pytest.mark.parametrize("body", ["", "No shipping details here", "Order W9999999999"])
def test_order_number_and_subject_alone_do_not_establish_an_event(
    method, subject, body
):
    result = getattr(AppleParser(), method)(
        f"<html><body>{body}</body></html>",
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )
    assert result == {}


@pytest.mark.parametrize(
    "method,subject,marker,number",
    [
        (
            "parse_confirmation",
            "Thank you for your order",
            "Thank you for your order",
            "W9999999999",
        ),
        (
            "parse_cancellation",
            "Information about your order",
            "Your order has been cancelled",
            "W9999999998",
        ),
        (
            "parse_shipment",
            "Your shipment is on its way",
            "Your shipment is on its way",
            "W9999999997",
        ),
    ],
)
def test_valid_order_view_link_supplies_missing_order_number(
    method, subject, marker, number
):
    href = f"https://store.apple.com/vieworder/{number}/buyer@example.test/"
    result = getattr(AppleParser(), method)(
        f'<p>{marker}</p><a href="{href}">View order</a>',
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result["order_number"] == number
    assert result["order_details_link"] == href


@pytest.mark.parametrize(
    "method,subject,marker",
    [
        (
            "parse_confirmation",
            "Thank you for your order",
            "Thank you for your order",
        ),
        (
            "parse_cancellation",
            "Information about your order",
            "Your order has been cancelled",
        ),
        (
            "parse_shipment",
            "Your shipment is on its way",
            "Your shipment is on its way",
        ),
    ],
)
@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example.test/vieworder/W9999999999/",
        "http://store.apple.com/vieworder/W9999999999/",
        "https://store.apple.com/notvieworder/W9999999999/",
        "https://store.apple.com/vieworder/W9999999999/../W9999999998/",
    ],
)
def test_hostile_order_view_link_cannot_supply_order_number(
    method, subject, marker, href
):
    result = getattr(AppleParser(), method)(
        f'<p>{marker}</p><a href="{href}">View order</a>',
        subject=subject,
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )

    assert result == {}


@pytest.mark.parametrize(
    "method,subject,marker,number",
    [
        (
            "process_apple_confirmation_email",
            "Thank you for your order",
            "Thank you for your order",
            "W9999999999",
        ),
        (
            "process_apple_cancellation_email",
            "Information about your order",
            "Your order has been cancelled",
            "W9999999998",
        ),
        (
            "process_apple_shipped_email",
            "Your shipment is on its way",
            "Your shipment is on its way",
            "W9999999997",
        ),
    ],
)
def test_processor_extracts_order_number_from_valid_link_only_email(
    method, subject, marker, number
):
    href = f"https://store.apple.com/vieworder/{number}/buyer@example.test/"
    result = getattr(EmailProcessor(), method)(link_only_email(subject, marker, href))

    assert result["order_number"] == number
    assert result["order_details_link"] == href


def test_processor_rejects_hostile_link_only_email():
    result = EmailProcessor().process_apple_confirmation_email(
        link_only_email(
            "Thank you for your order",
            "Thank you for your order",
            "https://evil.example.test/vieworder/W9999999999/",
        )
    )

    assert result == {}


@pytest.mark.parametrize(
    "marker", ["Your order has been cancelled", "YOUR ORDER HAS BEEN CANCELED"]
)
def test_cancellation_accepts_both_body_spellings(marker):
    html, subject, recipient = load_html("apple_cancellation.eml")
    result = AppleParser().parse_cancellation(
        html.replace("Your order has been cancelled", marker),
        subject=subject,
        email_address=recipient,
        email_date="2026-09-19",
    )
    assert result["order_number"] == "W9999999998"
    assert result["cancellation_type"] == "cancelled"


@pytest.mark.parametrize(
    "signal",
    [
        "<p>Your shipment is on its way</p>",
        "<table><tr><td>Carrier Name</td><td>UPS</td></tr></table>",
        "<table><tr><td>Tracking Number:</td><td>1Z999AA10123456784</td></tr></table>",
        "<table><tr><td>Delivers Sep 24, 2026 via UPS</td></tr></table>",
    ],
)
def test_shipment_accepts_body_evidence_with_optional_catalog_omitted(signal):
    result = AppleParser().parse_shipment(
        signal,
        subject="YOUR SHIPMENT IS ON ITS WAY W9999999997",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )
    assert result["order_number"] == "W9999999997"
    assert result["products"] == []


@pytest.mark.parametrize("label", ["Ordered on:", "Ordered On"])
@pytest.mark.parametrize("kind", ["confirmation", "shipment", "cancellation"])
def test_ordered_date_variants_override_notification_date(label, kind):
    html, subject, recipient = load_html(f"apple_{kind}.eml")
    result = getattr(AppleParser(), f"parse_{kind}")(
        html.replace("Ordered on", label),
        subject=subject,
        email_address=recipient,
        email_date="2026-09-19",
    )
    assert result["date"] == ("2026-04-23" if kind == "cancellation" else "2026-09-12")


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
@pytest.mark.parametrize("include_shipping", [True, False])
def test_shipping_location_never_uses_merchant_footer(kind, include_shipping):
    html, subject, recipient = load_html(f"apple_{kind}.eml")
    if not include_shipping:
        html = html.replace(
            "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>", ""
        )
    # A layout table must not allow a later merchant address to become shipping.
    html = html.replace("<body>", "<body><table><tr><td>").replace(
        "</body>",
        "<table class='footer'><tr><td>Cupertino CA 95014</td></tr></table></td></tr></table></body>",
    )
    result = getattr(AppleParser(), f"parse_{kind}")(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )
    assert result["shipping_city"] == ("Concord" if include_shipping else "")
    assert result["state"] == ("NH" if include_shipping else "")
    assert result["zip"] == ("03301" if include_shipping else "")


@pytest.mark.parametrize("label", ["Shipping Address:", "Ship To"])
def test_labeled_shipping_block_is_used_without_template_classes(label):
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = (
        html.replace('class="fulfillment"', "")
        .replace("<td>Example Buyer", f"<td>{label}</td><td>Example Buyer")
        .replace(
            "</body>", "<table><tr><td>Cupertino CA 95014</td></tr></table></body>"
        )
    )
    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )
    assert result["zip_and_state"] == "Concord, NH 03301"


def test_confirmation_extracts_same_cell_shipping_heading_without_table_class():
    html, subject, recipient = load_html("apple_confirmation.eml")
    address_row = (
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    )
    same_cell_row = "<tr><td>Shipping Address:<br>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    assert html.count('class="fulfillment"') == 1
    assert html.count(address_row) == 1
    html = (
        html.replace('class="fulfillment"', "", 1)
        .replace(address_row, same_cell_row, 1)
        .replace(
            "</body>",
            "<table><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table></body>",
        )
    )
    assert 'class="fulfillment"' not in html
    assert html.count(same_cell_row) == 1

    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["shipping_city"] == "Concord"
    assert result["state"] == "NH"
    assert result["zip"] == "03301"


def test_shipment_extracts_same_cell_shipping_heading_without_table_class():
    html, subject, recipient = load_html("apple_shipment.eml")
    address_row = (
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    )
    same_cell_row = "<tr><td>Shipping Address:<br>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    assert html.count('class="shipment-content"') == 1
    assert html.count(address_row) == 1
    html = (
        html.replace(
            '<table class="shipment-content">',
            "<table>",
        )
        .replace(
            address_row,
            same_cell_row,
            1,
        )
        .replace(
            "</body>",
            "<table><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table></body>",
        )
    )
    assert 'class="shipment-content"' not in html
    assert html.count(same_cell_row) == 1

    result = AppleParser().parse_shipment(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["shipping_city"] == "Concord"
    assert result["state"] == "NH"
    assert result["zip"] == "03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_missing_shipping_address_does_not_use_footer(kind):
    html, subject, recipient = load_html(f"apple_{kind}.eml")
    address_row = (
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    )
    table_class = "fulfillment" if kind == "confirmation" else "shipment-content"
    assert html.count(address_row) == 1
    assert html.count(f'class="{table_class}"') == 1
    html = html.replace(address_row, "", 1).replace(f'class="{table_class}"', "", 1)
    nested_missing_address = """
      <table class="layout-shell"><tr><td>
        <table class="shipping-card"><tr><td>Shipping Address:</td></tr></table>
        <table class="footer"><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table>
      </td></tr></table>
    """
    assert "Shipping Address:" not in html
    assert "Cupertino CA 95014" not in html
    assert "</body>" in html
    html = html.replace("</body>", nested_missing_address + "</body>", 1)
    assert html.count("Shipping Address:") == 1
    assert html.count("Cupertino CA 95014") == 1

    result = getattr(AppleParser(), f"parse_{kind}")(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["shipping_city"] == ""
    assert result["state"] == ""
    assert result["zip"] == ""
    assert result["zip_and_state"] == ""


def parse_minimal_location_case(kind, block):
    marker = (
        "Thank you for your order"
        if kind == "confirmation"
        else "Your shipment is on its way"
    )
    html = f"<p>{marker}</p>{block}"
    assert html.count(marker) == 1
    assert block in html
    assert html.count("W9999999999") == 0
    return getattr(AppleParser(), f"parse_{kind}")(
        html,
        subject=f"{marker} W9999999999",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_footer_in_incomplete_shipping_cell_is_ignored(kind):
    result = parse_minimal_location_case(
        kind,
        """<table><tr><td>Shipping Address:<br>Example Buyer<br>123 MAIN STREET
<table><tr><td>No destination available</td></tr></table>
<table class="footer"><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table>
</td></tr></table>""",
    )

    assert result["shipping_city"] == ""
    assert result["state"] == ""
    assert result["zip"] == ""
    assert result["zip_and_state"] == ""


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_adjacent_shipping_address_is_preserved(kind):
    buyer = "Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
    nested = f"<table><tr><td>{buyer}</td></tr></table>"
    block = f"<table><tr><td>Shipping Address:</td><td>{nested}</td></tr></table>"

    result = parse_minimal_location_case(kind, block)

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_next_row_shipping_address_is_preserved(kind):
    buyer = "Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
    nested = f"<table><tr><td>{buyer}</td></tr></table>"
    block = (
        f"<table><tr><td>Shipping Address:</td></tr><tr><td>{nested}</td></tr></table>"
    )

    result = parse_minimal_location_case(kind, block)

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize(
    "kind,table_class",
    [("confirmation", "fulfillment"), ("shipment", "shipment-content")],
)
def test_nested_template_shipping_address_is_preserved(kind, table_class):
    buyer = "Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
    nested = f"<table><tr><td>{buyer}</td></tr></table>"
    block = f'<table class="{table_class}"><tr><td>{nested}</td></tr></table>'

    result = parse_minimal_location_case(kind, block)

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_nested_footer_table_does_not_discard_valid_shipping_data(kind):
    html, subject, recipient = load_html(f"apple_{kind}.eml")
    address_row = (
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>"
    )
    nested_footer = (
        '<table class="footer"><tr><td>'
        "<table><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table>"
        "</td></tr></table>"
    )
    address_row_with_footer = (
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
        f"{nested_footer}</td></tr>"
    )
    assert html.count(address_row) == 1
    assert nested_footer not in html
    html = html.replace(address_row, address_row_with_footer, 1)
    assert html.count(address_row_with_footer) == 1
    assert html.count(nested_footer) == 1

    result = getattr(AppleParser(), f"parse_{kind}")(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )

    assert result["shipping_city"] == "Concord"
    assert result["state"] == "NH"
    assert result["zip"] == "03301"
    assert result["zip_and_state"] == "Concord, NH 03301"
    if kind == "shipment":
        assert result["tracking_numbers"] == ["1Z999AA10123456784"]


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
@pytest.mark.parametrize("layout", ["adjacent", "next_row"])
def test_split_inline_shipping_heading_is_normalized(kind, layout):
    buyer = "Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
    if layout == "adjacent":
        block = (
            f"<table><tr><td><b>Shipping</b> Address:</td><td>{buyer}</td></tr></table>"
        )
    else:
        block = (
            "<table><tr><td><b>Shipping</b> Address:</td></tr>"
            f"<tr><td>{buyer}</td></tr></table>"
        )

    result = parse_minimal_location_case(kind, block)

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_formatted_separate_shipping_label_keeps_adjacent_address(kind):
    result = parse_minimal_location_case(
        kind,
        """<table><tr><td><b>Shipping Address:</b></td>
<td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr></table>""",
    )

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
@pytest.mark.parametrize("layout", ["adjacent", "next_row"])
def test_formatted_label_with_external_colon_keeps_shipping_address(kind, layout):
    label = "<b>Shipping Address</b>:"
    buyer = "Example Buyer<br>123 MAIN STREET<br>Concord NH 03301"
    if layout == "adjacent":
        block = f"<table><tr><td>{label}</td><td>{buyer}</td></tr></table>"
    else:
        block = f"<table><tr><td>{label}</td></tr><tr><td>{buyer}</td></tr></table>"
    assert "<b>Shipping Address</b>:" in block

    result = parse_minimal_location_case(kind, block)

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_formatted_same_cell_shipping_label_keeps_buyer_address(kind):
    result = parse_minimal_location_case(
        kind,
        """<table><tr><td><b>Shipping Address:</b><br>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr></table>""",
    )

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize("kind", ["confirmation", "shipment"])
def test_wrapped_same_cell_shipping_address_stays_before_footer_row(kind):
    result = parse_minimal_location_case(
        kind,
        """<table><tr><td>Shipping Address:
<div>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</div></td></tr>
<tr><td><table class="footer"><tr><td>Merchant Contact<br>Cupertino CA 95014</td></tr></table></td></tr></table>""",
    )

    assert result["zip_and_state"] == "Concord, NH 03301"


@pytest.mark.parametrize(
    "url",
    [
        "https://store.apple.com/vieworder/W9999999999/buyer@example.test/",
        "https://secure.store.apple.com/xc/us/vieworder/W9999999999/buyer@example.test/",
    ],
)
def test_order_link_accepts_apple_https_detail_urls(url):
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace(
        "https://store.apple.com/vieworder/W9999999999/buyer@example.test/", url
    )
    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )
    assert result["order_details_link"] == url


@pytest.mark.parametrize(
    "url",
    [
        "https://untrusted.example.test/vieworder/W9999999999/",
        "https://store.apple.com.evil.example.test/vieworder/W9999999999/",
        "https://store.apple.com@evil.example.test/vieworder/W9999999999/",
        "https://evil.example.test@store.apple.com/vieworder/W9999999999/",
        "http://store.apple.com/vieworder/W9999999999/",
        "javascript:alert('vieworder/W9999999999')",
        "//store.apple.com/vieworder/W9999999999/",
        "https://store.apple.com:8443/vieworder/W9999999999/",
        "https://store.apple.com:notaport/vieworder/W9999999999/",
        "https://[invalid/vieworder/W9999999999/",
        "https://store.apple.com/vieworder/W99999999990/",
        "https://store.apple.com/vieworder/W9999999998/?order=W9999999999",
        "https://store.apple.com/notvieworder/W9999999999/",
        "https://store.apple.com/orders/?vieworder=W9999999999",
        "https://store.apple.com/vieworder/W9999999999/../W9999999998/",
        "https://store.apple.com/vieworder/W9999999999/%2e%2e/",
        "https://store.apple.com/vieworder/W9999999999/%2f..%2fW9999999998/",
        "https://store.apple.com/vieworder/W9999999999/%5c..%5cW9999999998/",
    ],
)
def test_order_link_rejects_untrusted_or_mismatched_urls(url):
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace(
        "https://store.apple.com/vieworder/W9999999999/buyer@example.test/", url
    )
    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-19"
    )
    assert result["order_details_link"] == ""


@pytest.mark.parametrize(
    "marker",
    [
        "We're processing your order",
        "We’re processing your order",
        "Thank you for your order",
    ],
)
def test_confirmation_body_marker_allows_optional_catalog_date_and_total(marker):
    result = AppleParser().parse_confirmation(
        f"<p>{marker}</p>",
        subject="Thank you for your order W9999999999",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )
    assert result["order_number"] == "W9999999999"
    assert result["date"] == "2026-09-19"
    assert result["products"] == []
    assert result["total_price"] == ""


@pytest.mark.parametrize("kind", ["confirmation", "cancellation", "shipment"])
def test_event_evidence_still_requires_an_order_number(kind):
    html, subject, recipient = load_html(f"apple_{kind}.eml")
    result = getattr(AppleParser(), f"parse_{kind}")(
        re.sub(r"W\d+", "", html),
        subject=re.sub(r"W\d+", "", subject),
        email_address=recipient,
        email_date="2026-09-19",
    )
    assert result == {}
