import json
import logging
import os
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class OrderParser:
    _config = None

    @classmethod
    def _load_config(cls):
        if cls._config is None:
            config_path = os.path.join(os.path.dirname(__file__), "html_selectors.json")
            with open(config_path, "r") as f:
                cls._config = json.load(f)
        return cls._config

    @classmethod
    def _find_elements(cls, soup, selector_config):
        config = selector_config
        tag = config["tag"]

        kwargs = {}
        if "attributes" in config:
            for attr, value in config["attributes"].items():
                if attr == "style_contains":
                    kwargs["style"] = lambda v, val=value: v and val in v
                elif attr == "style_contains_all":
                    kwargs["style"] = lambda v, val=value: (
                        v and all(part in v for part in val)
                    )
                elif attr == "href_contains":
                    kwargs["href"] = lambda v, val=value: v and val in v
                else:
                    kwargs[attr] = value

        elements = soup.find_all(tag, **kwargs)

        if "text_contains" in config:
            text_filter = config["text_contains"]
            elements = [elem for elem in elements if text_filter in elem.text]

        if "text_min_length" in config:
            min_length = config["text_min_length"]
            elements = [
                elem for elem in elements if len(elem.get_text().strip()) >= min_length
            ]

        return elements

    @classmethod
    def _find_element(cls, soup, selector_config):
        config = selector_config
        tag = config["tag"]

        kwargs = {}
        if "attributes" in config:
            for attr, value in config["attributes"].items():
                if attr == "style_contains":
                    kwargs["style"] = lambda v, val=value: v and val in v
                elif attr == "style_contains_all":
                    kwargs["style"] = lambda v, val=value: (
                        v and all(part in v for part in val)
                    )
                elif attr == "href_contains":
                    kwargs["href"] = lambda v, val=value: v and val in v
                else:
                    kwargs[attr] = value

        if "text_contains" in config or "text_min_length" in config:
            elements = soup.find_all(tag, **kwargs)

            if "text_contains" in config:
                text_filter = config["text_contains"]
                elements = [elem for elem in elements if text_filter in elem.text]

            if "text_min_length" in config:
                min_length = config["text_min_length"]
                elements = [
                    elem
                    for elem in elements
                    if len(elem.get_text().strip()) >= min_length
                ]

            return elements[0] if elements else None

        return soup.find(tag, **kwargs)

    @staticmethod
    def _extract_product_image(section) -> str:
        parent_row = section.find_parent("tr")
        if not parent_row:
            return ""
        img = parent_row.find("img", alt=lambda a: a and "Product Image For:" in a)
        if not img:
            img = parent_row.find(
                "img",
                src=lambda s: (
                    s and "bbystatic.com/image2/BestBuy_US/images/products/" in s
                ),
            )
        src = (img.get("src") or "").strip() if img else ""
        if src:
            logger.debug("Extracted Best Buy product image: %s", src[:120])
        return src

    @staticmethod
    def _is_xbox_item(title: str) -> bool:
        return "Xbox" in title or "Game Pass" in title

    @staticmethod
    def _is_skipped_perk(title: str) -> bool:
        return "fubo" in title or "Apple TV" in title or "Norton" in title

    @staticmethod
    def _parse_compact_product_rows(soup) -> List[Dict[str, str]]:
        """Parse the "We've got your order" layout (Oct 2026).

        Each item is a single row: product image | title link | price + "Qty: N".
        """
        items = []
        images = soup.find_all(
            "img",
            src=lambda s: s and "bbystatic.com/image2/BestBuy_US/images/products/" in s,
        )
        for img in images:
            row = img.find_parent("tr")
            if not row:
                continue
            title_tag = next(
                (a for a in row.find_all("a") if len(a.get_text(strip=True)) >= 10),
                None,
            )
            if not title_tag:
                continue

            price_span = row.find("span", string=lambda t: t and "$" in t)
            qty_span = row.find(
                "span", string=lambda t: t and t.strip().startswith("Qty:")
            )
            qty = (
                qty_span.get_text(strip=True).split(":", 1)[1].strip()
                if qty_span
                else ""
            )

            items.append(
                {
                    "title": title_tag.get_text(strip=True),
                    "quantity": qty or "1",
                    "price": price_span.get_text(strip=True) if price_span else "",
                    "model_number": "",
                    "item_image": (img.get("src") or "").strip(),
                }
            )
        return items

    @staticmethod
    def parse_product_details(
        html_content: str,
    ) -> Tuple[List[Dict[str, str]], str, List[Dict[str, str]]]:
        config = OrderParser._load_config()
        soup = BeautifulSoup(html_content, "lxml")
        products = []
        xbox_items = []

        product_config = config["product_parsing"]

        product_sections = OrderParser._find_elements(
            soup, product_config["product_sections"]
        )

        for section in product_sections:
            title_tag = OrderParser._find_element(section, product_config["title"])
            if not title_tag:
                continue

            title = title_tag.text.strip()
            item_image = OrderParser._extract_product_image(section)

            if OrderParser._is_skipped_perk(title):
                logger.debug("Skipping perk item: %s", title[:80])
                continue

            qty_tag = section.find_next("td", string="Qty:")
            qty = qty_tag.find_next_sibling("td").text.strip() if qty_tag else "N/A"

            model_tag = section.find_next(
                "td", string=lambda t: t and "Model" in t and "#" in t
            )
            model_number = ""
            if model_tag:
                model_val_td = model_tag.find_next_sibling("td")
                if model_val_td:
                    model_number = model_val_td.text.strip()

            dollar_spans = section.find_all(
                "span", string=lambda text: text and "$" in text
            )

            price_tag = section.find(
                product_config["price"]["tag"],
                string=lambda text: text and "$" in text,
                style=lambda value: (
                    value
                    and product_config["price"]["attributes"]["style_contains"] in value
                ),
            )

            if not price_tag and dollar_spans:
                for span in dollar_spans:
                    if "$" in span.text and span.text.strip() not in ["$0.00", "$"]:
                        price_tag = span
                        break

            price = price_tag.text.strip() if price_tag else "N/A"

            if OrderParser._is_xbox_item(title):
                xbox_items.append(
                    {
                        "title": title,
                        "quantity": qty if qty != "N/A" else "1",
                        "price": price if price != "N/A" else "",
                        "model_number": model_number,
                        "item_image": item_image,
                    }
                )
                logger.info("Scraped Xbox item from confirmation: %s", title[:80])
                continue

            products.append(
                {
                    "title": title,
                    "quantity": qty if qty != "N/A" else "1",
                    "price": "" if price == "N/A" else price,
                    "model_number": model_number,
                    "item_image": item_image,
                }
            )
            if item_image:
                logger.info("Scraped product image for: %s", title[:80])

        if not product_sections:
            for item in OrderParser._parse_compact_product_rows(soup):
                title = item["title"]
                if OrderParser._is_skipped_perk(title):
                    logger.debug("Skipping perk item: %s", title[:80])
                    continue
                if OrderParser._is_xbox_item(title):
                    xbox_items.append(item)
                    logger.info("Scraped Xbox item from confirmation: %s", title[:80])
                    continue
                products.append(item)

        total_td = OrderParser._find_element(soup, product_config["total"])
        if total_td and "$" not in total_td.text:
            # The newer layout styles the "Total" label like the amount cell.
            total_td = next(
                (
                    td
                    for td in OrderParser._find_elements(soup, product_config["total"])
                    if "$" in td.text
                ),
                total_td,
            )
        total_price = total_td.text.strip() if total_td else "N/A"

        return products, total_price, xbox_items

    @staticmethod
    def extract_order_number(soup: BeautifulSoup, email_type: str) -> str:
        config = OrderParser._load_config()
        order_config = config["order_number"]

        if email_type == "confirmation":
            order_span = OrderParser._find_element(soup, order_config["confirmation"])
            if order_span:
                return order_span.text.strip()
            # Newer confirmations render the order number as a link, not a span.
            import re

            match = re.search(r"BBY\d{2}-\d{9,15}", soup.get_text(" "))
            return match.group(0) if match else None

        if email_type == "cancellation":
            cancelled_config = order_config["cancelled"]
            order_tds = OrderParser._find_elements(soup, cancelled_config["container"])
            for td in order_tds:
                if cancelled_config["container"]["text_contains"] in td.text:
                    order_span = td.find(
                        cancelled_config["target"]["tag"],
                        style=lambda value: (
                            value
                            and all(
                                part in value
                                for part in cancelled_config["target"]["attributes"][
                                    "style_contains_all"
                                ]
                            )
                        ),
                    )
                    if order_span:
                        return order_span.text.strip()

        order_span = OrderParser._find_element(soup, order_config["shipped_cancelled"])
        if order_span:
            text = order_span.text.strip()
            replace_config = order_config["shipped_cancelled"]["text_replace"]
            return text.replace(replace_config["from"], replace_config["to"])

        alt_config = order_config["alternative"]
        order_tds = OrderParser._find_elements(soup, alt_config["container"])
        for td in order_tds:
            if alt_config["container"]["text_contains"] in td.text:
                order_span = td.find(
                    alt_config["target"]["tag"],
                    style=lambda value: (
                        value
                        and all(
                            part in value
                            for part in alt_config["target"]["attributes"][
                                "style_contains_all"
                            ]
                        )
                    ),
                )
                if order_span:
                    return order_span.text.strip()

        # Fallback to regex for order number if HTML selectors fail
        import re

        html_content = str(soup)
        match = re.search(r"BBY\d{2}-\d{9,15}", html_content)
        if match:
            return match.group(0)

        return None

    @staticmethod
    def extract_tracking_numbers(soup: BeautifulSoup) -> List[str]:
        config = OrderParser._load_config()
        tracking_config = config["tracking_numbers"]
        tracking_numbers = []

        format1_config = tracking_config["format_1"]
        tracking_spans = soup.find_all(
            format1_config["container"]["tag"],
            **format1_config["container"]["attributes"],
        )
        print(f"     Format 1 - Found {len(tracking_spans)} potential tracking spans")
        for span in tracking_spans:
            if format1_config["container"]["text_contains"] in span.text:
                tracking_link = span.find(format1_config["target"]["tag"])
                if tracking_link:
                    tracking_num = tracking_link.text.strip()
                    print(f"     ✓ Format 1 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        format2_config = tracking_config["format_2"]
        tracking_tds = OrderParser._find_elements(soup, format2_config["container"])
        print(f"     Format 2 - Found {len(tracking_tds)} potential tracking TDs")
        for td in tracking_tds:
            if format2_config["container"]["text_contains"] in td.text:
                print("     Format 2 - Text match found in TD")
                tracking_span = td.find(
                    format2_config["target"]["tag"],
                    style=lambda value: (
                        value
                        and all(
                            part in value
                            for part in format2_config["target"]["attributes"][
                                "style_contains_all"
                            ]
                        )
                    ),
                )
                if tracking_span:
                    tracking_num = tracking_span.text.strip()
                    print(f"     ✓ Format 2 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        format3_config = tracking_config["format_3"]
        tracking_tds = OrderParser._find_elements(soup, format3_config["container"])
        print(f"     Format 3 - Found {len(tracking_tds)} potential tracking TDs")
        for td in tracking_tds:
            if format3_config["container"]["text_contains"] in td.text:
                print("     Format 3 - Text match found in TD")
                tracking_span = td.find(
                    format3_config["target"]["tag"],
                    style=lambda value: (
                        value
                        and all(
                            part in value
                            for part in format3_config["target"]["attributes"][
                                "style_contains_all"
                            ]
                        )
                    ),
                )
                if tracking_span:
                    tracking_num = tracking_span.text.strip()
                    print(f"     ✓ Format 3 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        if not tracking_numbers:
            all_tds_with_tracking = soup.find_all(
                "td", string=lambda text: text and "tracking" in text.lower()
            )
            if all_tds_with_tracking:
                print(
                    f"     ⚠ Found {len(all_tds_with_tracking)} TDs containing 'tracking' but couldn't extract numbers"
                )
                for td in all_tds_with_tracking[:3]:
                    print(f"       Sample: {td.text.strip()[:100]}")

        if not tracking_numbers:
            all_tds_with_tracking = soup.find_all(
                "td", string=lambda text: text and "tracking" in text.lower()
            )
            if all_tds_with_tracking:
                print(
                    f"     ⚠ Found {len(all_tds_with_tracking)} TDs containing 'tracking' but couldn't extract numbers"
                )
                for td in all_tds_with_tracking[:3]:
                    print(f"       Sample: {td.text.strip()[:100]}")

        return tracking_numbers

    @staticmethod
    def _location_line(text: str) -> str:
        if not text:
            return ""
        try:
            from services.location import location_found, parse_location

            parsed = parse_location(text)
            if location_found(parsed):
                logger.debug(
                    "Extracted location state=%s zip=%s",
                    parsed["state"],
                    parsed["zip"],
                )
                return parsed["zip_and_state"] or text
        except ImportError:
            if ", " in text and any(char.isdigit() for char in text):
                logger.debug("Extracted location with local city/state/zip heuristic")
                return text
        return ""

    @staticmethod
    def extract_shipping_address(soup: BeautifulSoup) -> str:
        logger.debug("Starting shipping address extraction")
        shipping_tds = soup.find_all("td")
        old_format_tds = [
            td for td in shipping_tds if "Your order is shipping to:" in td.get_text()
        ]
        logger.debug(
            f"Old format - Found {len(old_format_tds)} TDs with 'Your order is shipping to:'"
        )

        for td in old_format_tds:
            spans = td.find_all("span")
            logger.debug(f"Old format - Found {len(spans)} spans in TD")

            for span in spans:
                span_text = span.get_text().strip()
                span_style = span.get("style", "")

                is_address = (
                    len(span_text.split()) > 3
                    and ("," in span_text or "<br>" in str(span))
                    and any(char.isdigit() for char in span_text)
                    and not span_text.lower().startswith(
                        ("status", "ready", "product", "shipped", "delivered")
                    )
                )

                has_style = (
                    "font-size: 20px" in span_style and "font-weight: 700" in span_style
                ) or ("font-weight: 700" in span_style and "font-size" in span_style)

                logger.debug(
                    f"Old format - Span text: '{span_text[:50]}...' | is_address: {is_address} | has_style: {has_style}"
                )

                if is_address and has_style:
                    address_text = span.get_text(separator="\n")
                    lines = [
                        line.strip()
                        for line in address_text.split("\n")
                        if line.strip()
                    ]
                    logger.debug(f"Old format - Address lines: {lines}")

                    last_line = lines[-1] if lines else ""
                    logger.debug(f"Old format - Last line: '{last_line}'")
                    location = OrderParser._location_line(last_line)
                    if location:
                        return location

        new_format_tds = [
            td
            for td in shipping_tds
            if "Shipping to:" in td.get_text()
            and "Your order is shipping to:" not in td.get_text()
        ]
        logger.debug(
            f"New format - Found {len(new_format_tds)} TDs with 'Shipping to:'"
        )

        for td in new_format_tds:
            parent = td.find_parent("tr")
            if parent:
                next_row = parent.find_next_sibling("tr")
                if next_row:
                    address_span = next_row.find(
                        "span", style=lambda v: v and "font-size: 16px" in v
                    )
                    if address_span:
                        address_text = address_span.get_text(separator="\n").strip()
                        logger.debug(f"New format - Address text: '{address_text}'")
                        location = OrderParser._location_line(address_text)
                        if location:
                            return location

        logger.warning("No state/zip found in shipping address")
        return ""

    @staticmethod
    def extract_order_details_link(soup: BeautifulSoup) -> str:
        config = OrderParser._load_config()
        if "details_link" not in config:
            print("     ⚠ 'details_link' not found in config")
            return ""

        details_link_config = config["details_link"]["confirmation"]
        link_tag = OrderParser._find_element(soup, details_link_config)

        if link_tag:
            href = link_tag.get("href")
            if href:
                print(f"     ✓ Extracted order details link: {href[:50]}...")
                return href
            else:
                print(
                    "     ⚠ Found link tag for 'View order details' but it has no href"
                )
        else:
            print("     ⚠ Could not find 'View order details' link tag")

        return ""
