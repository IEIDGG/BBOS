from pathlib import Path

from email_processing.parsers.apple_parser import AppleParser


def parse():
    return AppleParser().parse_shipment(
        (Path(__file__).parent / "fixtures/apple_live_layout.html").read_text(),
        subject="Your shipment is on its way W9999999997",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )


def test_live_product_layout_keeps_title_quantity_price_and_image():
    assert parse()["products"] == [
        {
            "title": "iPhone 18 Pro Max 256GB Black",
            "quantity": "1",
            "price": "$1,299.00",
            "item_image": "https://store.storeimages.cdn-apple.com/1/as-images.apple.com/is/iphone-black?wid=192&hei=192",
        }
    ]


def test_live_heading_layout_extracts_shipping_not_mobile_carrier():
    result = parse()
    assert result["carrier"] == "UPS"
    assert result["tracking_numbers"] == ["1Z999AA10123456784"]
    assert result["estimated_delivery"] == "Sep 23, 2026"


def test_live_address_excludes_masked_phone_and_other_sections():
    assert (
        parse()["shipping_address"]
        == "Example Buyer, 123 MAIN STREET, STE 7, Concord NH 03301"
    )


def test_live_confirmation_totals_delivery_and_order_date_layout():
    result = AppleParser().parse_confirmation(
        """
      <div class="order-num"><span>Ordered on:</span><span>Sep 12, 2026</span></div>
      <table><tr><td><div>Shipment 1</div><div><span>Delivers:</span> Sep 29 – Oct 6 by Express Delivery</div></td></tr></table>
      <table><tr><td>
        <table class="amt-label-table"><tr><td>Order Total</td></tr></table>
        <table class="amt-value-table"><tr><td>$1,299.00</td></tr></table>
      </td></tr></table>""",
        subject="We're processing your order W9999999999",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )
    assert result["date"] == "2026-09-12"
    assert result["total_price"] == "$1,299.00"
    assert result["estimated_delivery"] == "Sep 29 – Oct 6"


def test_shipment_order_link_accepts_apple_campaign_suffix():
    result = AppleParser().parse_shipment(
        """<a href="https://store.apple.com/vieworder/W9999999997/buyer@example.test/AOS-AM-110137-N2496-A10000078573">View order</a><p>Your shipment is on its way</p>""",
        subject="Your shipment is on its way W9999999997",
        email_address="buyer@example.test",
        email_date="2026-09-19",
    )
    assert result["order_details_link"].endswith("/AOS-AM-110137-N2496-A10000078573")
