from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from config.settings import COSTCO_SEARCH_CRITERIA
from email_processing.parsers.costco_parser import CostcoParser
from email_processing.processor import EmailProcessor

FIXTURES = Path(__file__).parent / "fixtures"


def load_email_data(name: str) -> tuple[bytes, bytes]:
    return (b"fixture-" + name.encode(), (FIXTURES / name).read_bytes())


def test_costco_search_criteria_match_orders_costco_sender():
    for email_type in ("confirmation", "shipped"):
        assert "Costco@orders.costco.com" in COSTCO_SEARCH_CRITERIA[email_type]["from"]
    assert (
        '(SUBJECT "is confirmed")' in COSTCO_SEARCH_CRITERIA["confirmation"]["subject"]
    )
    assert '(SUBJECT "has shipped")' in COSTCO_SEARCH_CRITERIA["shipped"]["subject"]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1234567890", True),
        ("1300000001", True),
        ("1100000001", False),
        ("130000000", False),
        ("111000000001", False),
        ("13000000AB", False),
    ],
)
def test_order_number_validation_accepts_13_prefix(value, expected):
    assert CostcoParser._is_valid_costco_order_number(value) is expected


@pytest.mark.parametrize(
    "subject, email_type, expected",
    [
        (
            "Your Costco.com order 1300000001 is confirmed!",
            "confirmation",
            "1300000001",
        ),
        (
            "Your Costco.com Order Number 1234567890 is Confirmed",
            "confirmation",
            "1234567890",
        ),
        ("Fwd: Your Costco.com order 1300000002 has shipped!", "shipped", "1300000002"),
    ],
)
def test_order_number_from_subject(subject, email_type, expected):
    assert CostcoParser.extract_order_number_from_subject(subject, email_type) == (
        expected
    )


def test_new_template_confirmation_email():
    result = EmailProcessor().process_costco_confirmation_email(
        load_email_data("costco_confirmation.eml")
    )

    assert result["order_number"] == "1300000001"
    assert result["date"] == "2026-10-31"
    assert result["membership_number"] == "111000000001"
    assert result["total_price"] == "$2,699.98"
    assert result["price_summary"] == {
        "subtotal": "$2,699.98",
        "shipping": "$0.00",
        "tax": "$0.00",
        "total": "$2,699.98",
    }
    assert len(result["products"]) == 1
    product = result["products"][0]
    assert product["title"].startswith("MacBook Pro Laptop (14-inch) - Apple M5 chip")
    assert product["item_number"] == "1945139"
    assert product["price"] == "$1,349.99"
    assert product["quantity"] == "2"
    assert product["item_image"].startswith("https://gdx-assets.costco.com/")
    assert result["item_image"] == product["item_image"]


def test_new_template_order_placed_date_is_iso():
    html = (FIXTURES / "costco_confirmation.eml").read_text()
    soup = BeautifulSoup(html, "lxml")
    assert CostcoParser.extract_order_date(soup) == "2026-10-31"


def test_new_template_shipped_email():
    result = EmailProcessor().process_costco_shipped_email(
        load_email_data("costco_shipment.eml")
    )

    assert result["order_number"] == "1300000002"
    assert result["tracking_numbers"] == ["1Z999AA10123456784"]
