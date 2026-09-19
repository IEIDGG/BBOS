import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from config.settings import APPLE_SEARCH_CRITERIA
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


def test_apple_search_criteria_cover_all_email_types():
    assert set(APPLE_SEARCH_CRITERIA) == {"confirmation", "cancellation", "shipped"}
    assert "orders.apple.com" in APPLE_SEARCH_CRITERIA["confirmation"]["from"]
    assert "Your shipment is on its way" in APPLE_SEARCH_CRITERIA["shipped"]["subject"]


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
    assert html.count("Shipping Address") == 1
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
def test_formatted_separate_shipping_label_keeps_adjacent_address(kind):
    result = parse_minimal_location_case(
        kind,
        """<table><tr><td><b>Shipping Address:</b></td>
<td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr></table>""",
    )

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
