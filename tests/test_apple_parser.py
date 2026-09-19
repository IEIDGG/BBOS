from email import policy
from email.parser import BytesParser
from pathlib import Path

from email_processing.parsers.apple_parser import AppleParser


FIXTURES = Path(__file__).parent / "fixtures"


def load_html(name: str) -> tuple[str, str, str]:
    message = BytesParser(policy=policy.default).parsebytes(
        (FIXTURES / name).read_bytes()
    )
    html_part = next(
        part for part in message.walk() if part.get_content_type() == "text/html"
    )
    html = html_part.get_content()
    return html, message["Subject"], message["To"]


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


def test_confirmation_without_address_or_footer_has_empty_location_fields():
    html, subject, recipient = load_html("apple_confirmation.eml")
    html = html.replace(
        "<tr><td>Example Buyer<br>123 MAIN STREET<br>Concord NH 03301</td></tr>", ""
    ).replace(
        '<a href="https://secure.example.test/vieworder/W9999999999/buyer@example.test/">View order</a>',
        "",
    )

    result = AppleParser().parse_confirmation(
        html, subject=subject, email_address=recipient, email_date="2026-09-12"
    )

    assert result["shipping_city"] == ""
    assert result["state"] == ""
    assert result["zip"] == ""
    assert result["order_details_link"] == ""
