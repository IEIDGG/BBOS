import email
import importlib
import logging
import re
from datetime import datetime
from email.header import decode_header
from typing import Any, Dict, Optional, Tuple

from bs4 import BeautifulSoup

from .parsers.amazon_parser import AmazonParser
from .parsers.bb_parser import OrderParser
from .parsers.costco_parser import CostcoParser
from .parsers.xbox_parser import XboxParser

logger = logging.getLogger(__name__)


def _load_optional_parser(module_name: str, class_name: str):
    try:
        module = importlib.import_module(f".parsers.{module_name}", __package__)
        parser_cls = getattr(module, class_name)
        return parser_cls()
    except ImportError:
        logger.warning(
            "Optional parser %s.%s is not available", module_name, class_name
        )
        return None


_BESTBUY_LOCATION_RE = re.compile(
    r"\b(?P<city>[A-Za-z][A-Za-z .'-]*?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)\b"
)
_BESTBUY_STATE_ZIP_RE = re.compile(r"^([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$")
_BESTBUY_DELIVERY_RE = re.compile(
    r"Estimated\s+delivery\s*:?\s*(?P<delivery>(?:[A-Za-z]+,\s*)?[A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _location_from_text(value: str) -> Dict[str, str]:
    text = _normalize_text(value)
    match = _BESTBUY_LOCATION_RE.search(text)
    if match:
        city = _normalize_text(match.group("city"))
        state = match.group("state")
        zip_code = match.group("zip")
        return {
            "shipping_city": city,
            "state": state,
            "zip": zip_code,
            "zip_and_state": f"{city}, {state} {zip_code}",
        }

    match = _BESTBUY_STATE_ZIP_RE.match(text)
    if match:
        state = match.group(1)
        zip_code = match.group(2)
        return {
            "state": state,
            "zip": zip_code,
            "zip_and_state": f"{state} {zip_code}",
        }
    return {}


def _fallback_bestbuy_fulfillment(
    html_content: str, soup: BeautifulSoup, order_parser: OrderParser
) -> Dict[str, str]:
    details: Dict[str, str] = {}

    try:
        address_info = order_parser.extract_shipping_address(soup)
        details.update(_location_from_text(address_info))
    except Exception as exc:
        logger.debug("Best Buy fallback address extraction failed: %s", exc)

    text = _normalize_text(
        soup.get_text(" ")
        if soup is not None
        else BeautifulSoup(html_content or "", "html.parser").get_text(" ")
    )
    if not details.get("state"):
        details.update(_location_from_text(text))

    delivery_match = _BESTBUY_DELIVERY_RE.search(text)
    if delivery_match:
        details["estimated_delivery"] = _normalize_text(
            delivery_match.group("delivery")
        )

    return details


def _extract_bestbuy_fulfillment(
    html_content: str, soup: BeautifulSoup, order_parser: OrderParser
) -> Dict[str, str]:
    try:
        bestbuy_parser = importlib.import_module("services.bestbuy_email_parser")
        extractor = getattr(
            bestbuy_parser, "extract_bestbuy_confirmation_fulfillment", None
        )
        if callable(extractor):
            return extractor(html_content, soup) or {}

        parser = getattr(bestbuy_parser, "parse_bestbuy_fulfillment_details", None)
        if callable(parser):
            return parser(html_content) or {}

        logger.warning(
            "Best Buy fulfilment helper is not available; using local fallback"
        )
    except Exception as exc:
        logger.warning(
            "Best Buy fulfilment helper import failed; using local fallback: %s", exc
        )

    return _fallback_bestbuy_fulfillment(html_content, soup, order_parser)


class EmailProcessor:
    def __init__(self):
        self.order_parser = OrderParser()
        self.xbox_parser = XboxParser()
        self.costco_parser = CostcoParser()
        self.amazon_parser = AmazonParser()
        self.walmart_parser = _load_optional_parser("walmart_parser", "WalmartParser")

    def _parse_email_metadata(
        self, email_data: tuple
    ) -> Tuple[str, str, Optional[str]]:
        if isinstance(email_data, tuple):
            email_body = email_data[1]
        else:
            email_body = email_data

        if isinstance(email_body, bytes):
            email_message = email.message_from_bytes(email_body)
        else:
            email_message = email.message_from_string(str(email_body))

        email_address = email_message["To"]

        raw_subject = email_message["Subject"]
        decoded_parts = decode_header(raw_subject)
        subject_parts = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                if encoding:
                    try:
                        subject_parts.append(content.decode(encoding))
                    except Exception:
                        subject_parts.append(content.decode("utf-8", errors="ignore"))
                else:
                    subject_parts.append(content.decode("utf-8", errors="ignore"))
            else:
                subject_parts.append(str(content))
        subject = "".join(subject_parts)

        date_tuple = email.utils.parsedate_tz(email_message["Date"])
        if date_tuple:
            email_date = datetime.fromtimestamp(
                email.utils.mktime_tz(date_tuple)
            ).strftime("%Y-%m-%d")
        else:
            email_date = "Unknown"

        html_content = None
        content_types = []

        for part in email_message.walk():
            content_type = part.get_content_type()
            content_types.append(content_type)
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    try:
                        html_content = payload.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            html_content = payload.decode("latin-1")
                        except UnicodeDecodeError:
                            print("Warning: Could not decode email content")
                            continue
                elif payload is not None:
                    html_content = str(payload)
                break

        print(f"  📧 Subject: {subject[:60]}{'...' if len(subject) > 60 else ''}")
        print(f"     Date: {email_date} | To: {email_address}")
        print(
            f"     Parts: {', '.join(set(content_types))} | HTML: {'✓' if html_content else '✗'}"
        )

        return email_address, email_date, html_content

    def _bestbuy_catalog_fields(self, html_content: str, soup: BeautifulSoup) -> Dict:
        products, total_price, xbox_items = self.order_parser.parse_product_details(
            html_content
        )
        order_details_link = self.order_parser.extract_order_details_link(soup)
        item_image = next(
            (p.get("item_image") for p in products if p.get("item_image")),
            "",
        )
        if xbox_items and not item_image:
            item_image = next(
                (p.get("item_image") for p in xbox_items if p.get("item_image")),
                "",
            )
        fulfillment = _extract_bestbuy_fulfillment(
            html_content, soup, self.order_parser
        )
        return {
            "products": products,
            "xbox_items": xbox_items,
            "item_image": item_image,
            "total_price": total_price,
            "order_details_link": order_details_link,
            "state": fulfillment.get("state", ""),
            "zip": fulfillment.get("zip", ""),
            "zip_and_state": fulfillment.get("zip_and_state", ""),
            "shipping_city": fulfillment.get("shipping_city", ""),
            "estimated_delivery": fulfillment.get("estimated_delivery", ""),
            "address_info": fulfillment.get("zip_and_state", ""),
        }

    def process_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                print("Warning: No HTML content found in email")
                return {}

            soup = BeautifulSoup(html_content, "lxml")
            order_number = self.order_parser.extract_order_number(soup, "confirmation")
            if not order_number:
                print("Warning: Could not extract order number")
                return {}

            products, total_price, xbox_items = self.order_parser.parse_product_details(
                html_content
            )
            order_details_link = self.order_parser.extract_order_details_link(soup)
            item_image = next(
                (p.get("item_image") for p in products if p.get("item_image")), ""
            )
            if item_image:
                logger.info(
                    "Best Buy confirmation %s: scraped item_image", order_number
                )
            if xbox_items:
                logger.info(
                    "Best Buy confirmation %s: scraped %s Xbox item(s)",
                    order_number,
                    len(xbox_items),
                )

            fulfillment = _extract_bestbuy_fulfillment(
                html_content, soup, self.order_parser
            )
            if fulfillment.get("state"):
                logger.info(
                    "Best Buy confirmation %s: state=%s zip=%s",
                    order_number,
                    fulfillment.get("state"),
                    fulfillment.get("zip"),
                )
            elif fulfillment.get("estimated_delivery"):
                logger.info(
                    "Best Buy confirmation %s: estimated_delivery=%s (no zip/state)",
                    order_number,
                    fulfillment.get("estimated_delivery"),
                )
            else:
                logger.warning(
                    "Best Buy confirmation %s: no zip/state or delivery date found",
                    order_number,
                )

            return {
                "date": email_date,
                "order_number": order_number,
                "products": products,
                "xbox_items": xbox_items,
                "item_image": item_image,
                "total_price": total_price,
                "email_address": email_address,
                "order_details_link": order_details_link,
                "state": fulfillment.get("state", ""),
                "zip": fulfillment.get("zip", ""),
                "zip_and_state": fulfillment.get("zip_and_state", ""),
                "estimated_delivery": fulfillment.get("estimated_delivery", ""),
            }
        except Exception as e:
            print(f"Error processing confirmation email: {str(e)}")
            return {}

    def process_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, "lxml")
            order_number = self.order_parser.extract_order_number(soup, "cancelled")
            cancellation_type = (
                "payment_declined"
                if self._is_bestbuy_payment_update(subject, html_content)
                else "cancelled"
            )
            catalog = self._bestbuy_catalog_fields(html_content, soup)
            if catalog.get("products"):
                logger.info(
                    "Best Buy cancellation %s: scraped %s product(s)",
                    order_number,
                    len(catalog["products"]),
                )
            else:
                logger.warning(
                    "Best Buy cancellation %s: no product details found",
                    order_number,
                )

            return {
                "date": email_date,
                "order_number": order_number,
                "cancellation_type": cancellation_type,
                "subject": subject,
                "email_address": email_address,
                **catalog,
            }
        except Exception as e:
            print(f"Error processing cancellation email: {str(e)}")
            return {}

    def _is_bestbuy_payment_update(self, subject: str, html_content: str = "") -> bool:
        text = f"{subject or ''} {html_content or ''}".lower()
        return (
            "update your payment information" in text
            or "payment information needs to be updated" in text
            or "payment method was declined" in text
            or "payment was declined" in text
        )

    def process_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, "lxml")
            order_number = self.order_parser.extract_order_number(soup, "shipped")
            if not order_number:
                return {}

            tracking_numbers = self.order_parser.extract_tracking_numbers(soup)
            catalog = self._bestbuy_catalog_fields(html_content, soup)
            address_info = catalog.get(
                "zip_and_state"
            ) or self.order_parser.extract_shipping_address(soup)
            if catalog.get("zip_and_state"):
                logger.info(
                    "Best Buy shipped %s: location=%s",
                    order_number,
                    catalog.get("zip_and_state"),
                )
            else:
                logger.warning(
                    "Best Buy shipped %s: no city/state/zip found", order_number
                )
            if catalog.get("products"):
                logger.info(
                    "Best Buy shipped %s: scraped %s product(s)",
                    order_number,
                    len(catalog["products"]),
                )
            elif catalog.get("xbox_items"):
                logger.info(
                    "Best Buy shipped %s: scraped %s Xbox item(s)",
                    order_number,
                    len(catalog["xbox_items"]),
                )
            else:
                logger.warning(
                    "Best Buy shipped %s: no product details found", order_number
                )

            return {
                "date": email_date,
                "order_number": order_number,
                "email_address": email_address,
                **catalog,
                "tracking_numbers": tracking_numbers,
                "address_info": address_info,
            }
        except Exception as e:
            print(f"Error processing shipped email: {str(e)}")
            logger.error("Error processing shipped email: %s", e)
            return {}

    def process_price_match_credit_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            # Extract order number (e.g. BBY01-807154635113)
            order_number = None
            order_number_label = soup.find(
                string=re.compile(r"Order number:", re.IGNORECASE)
            )
            if order_number_label:
                parent = (
                    order_number_label.parent if order_number_label.parent else None
                )
                if parent:
                    bold = parent.find_next(
                        "span",
                        style=re.compile(
                            r"font-weight.*700|font-weight.*bold", re.IGNORECASE
                        ),
                    )
                    if bold:
                        order_number = bold.get_text(strip=True)
            if not order_number:
                match = re.search(r"BBY\d{2}-\d{9,15}", html_content)
                if match:
                    order_number = match.group(0)

            if not order_number:
                print(
                    "Warning: Could not extract order number from price match credit email"
                )
                return {}

            # Extract credit amount (e.g. $100.00)
            amount_saved = None
            credit_match = re.search(
                r"credit of \$([0-9]+(?:\.[0-9]{2})?)", html_content
            )
            if credit_match:
                amount_saved = credit_match.group(1)
            if not amount_saved:
                credit_match = re.search(
                    r"\$([0-9]+(?:\.[0-9]{2})?).*(?:credit|price difference)",
                    html_content,
                    re.IGNORECASE,
                )
                if credit_match:
                    amount_saved = credit_match.group(1)

            if not amount_saved:
                print(
                    "Warning: Could not extract credit amount from price match credit email"
                )
                return {}

            # Extract product name
            product_name = ""
            # Strategy 1: img alt text (most reliable, always present)
            img_tag = soup.find(
                "img", alt=re.compile(r"Product Image For:", re.IGNORECASE)
            )
            if img_tag:
                alt_text = img_tag.get("alt", "")
                product_name = re.sub(
                    r"^Product Image For:\s*", "", alt_text, flags=re.IGNORECASE
                ).strip()

            # Strategy 2 fallback: link text near "Return Product Details" section
            if not product_name:
                section_header = soup.find(
                    string=re.compile(r"Return Product Details", re.IGNORECASE)
                )
                if section_header:
                    parent_table = section_header.find_parent("table")
                    if parent_table:
                        link = parent_table.find_next("a", string=True)
                        if link:
                            product_name = link.get_text(strip=True)

            # Extract quantity
            quantity = 1
            qty_label = soup.find(
                "td", string=re.compile(r"^\s*Qty:\s*$", re.IGNORECASE)
            )
            if qty_label:
                qty_value = qty_label.find_next_sibling("td")
                if qty_value:
                    try:
                        quantity = int(qty_value.get_text(strip=True))
                    except ValueError:
                        quantity = 1

            print(
                f"  Price match credit: Order {order_number} - ${amount_saved} - {product_name or 'Unknown'} x{quantity}"
            )
            return {
                "date": email_date,
                "order_number": order_number,
                "amount_saved": amount_saved,
                "product_name": product_name or "",
                "quantity": quantity or 1,
                "email_address": email_address,
            }
        except Exception as e:
            print(f"Error processing price match credit email: {str(e)}")
            return {}

    def process_xbox_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            result = self.xbox_parser.extract_xbox_code(html_content)
            if not result:
                return {}

            cleaned_email = (email_address or "").strip()
            if cleaned_email.startswith("<") and cleaned_email.endswith(">"):
                cleaned_email = cleaned_email[1:-1].strip()
            elif "<" in cleaned_email and ">" in cleaned_email:
                match = re.search(r"<([^>]+)>", cleaned_email)
                if match:
                    cleaned_email = match.group(1).strip()

            result["email_address"] = cleaned_email
            result["date"] = email_date
            logger.info(
                "Xbox email processed: code=%s email=%s date=%s",
                result.get("code"),
                result.get("email_address"),
                email_date,
            )
            return result
        except Exception as e:
            logger.error("Error processing Xbox email: %s", e)
            print(f"Error processing Xbox email: {str(e)}")
            return {}

    def process_costco_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            if "Confirmed" not in subject and "confirmed" not in subject.lower():
                logger.debug(f"Skipping non-confirmation email: {subject[:50]}")
                return {}

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                logger.warning("No HTML content found in Costco confirmation email")
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.costco_parser.extract_order_number(
                soup, "confirmation", subject
            )
            if not order_number:
                logger.warning("Could not extract Costco order number")
                return {}

            order_date = self.costco_parser.extract_order_date(soup)
            membership_number = self.costco_parser.extract_membership_number(soup)
            shipping_address = self.costco_parser.extract_shipping_address(soup)
            products, total_price = self.costco_parser.parse_product_details(
                html_content
            )
            price_summary = self.costco_parser.extract_price_summary(soup)
            item_image = next(
                (p.get("item_image") for p in products if p.get("item_image")), ""
            )
            if item_image:
                logger.info("Costco confirmation %s: scraped item_image", order_number)

            return {
                "date": order_date or email_date,
                "order_number": order_number,
                "membership_number": membership_number,
                "shipping_address": shipping_address,
                "products": products,
                "item_image": item_image,
                "total_price": total_price,
                "price_summary": price_summary,
                "email_address": email_address,
                "state": shipping_address.get("state", ""),
                "zip": shipping_address.get("zip", ""),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Costco confirmation email: {str(e)}")
            return {}

    def process_costco_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            if (
                "Cancelled" not in subject
                and "cancelled" not in subject.lower()
                and "Canceled" not in subject
                and "canceled" not in subject.lower()
            ):
                logger.debug(f"Skipping non-cancellation email: {subject[:50]}")
                return {}

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.costco_parser.extract_order_number(
                soup, "cancellation", subject
            )
            cancellation_date = self.costco_parser.extract_cancellation_date(soup)

            return {
                "date": email_date,
                "order_number": order_number,
                "cancellation_date": cancellation_date,
                "email_address": email_address,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Costco cancellation email: {str(e)}")
            return {}

    def process_costco_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            if "Shipped" not in subject and "shipped" not in subject.lower():
                logger.debug(f"Skipping non-shipped email: {subject[:50]}")
                return {}

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.costco_parser.extract_order_number(
                soup, "shipped", subject
            )
            if not order_number:
                return {}

            tracking_numbers = self.costco_parser.extract_tracking_numbers(
                soup, html_content
            )
            shipping_address = self.costco_parser.extract_shipping_address(soup)

            return {
                "date": email_date,
                "order_number": order_number,
                "tracking_numbers": tracking_numbers,
                "state": shipping_address.get("state", ""),
                "zip": shipping_address.get("zip", ""),
                "email_address": email_address,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Costco shipped email: {str(e)}")
            return {}

    def _extract_subject(self, email_data: tuple) -> str:
        try:
            if isinstance(email_data, tuple):
                email_body = email_data[1]
            else:
                email_body = email_data

            if isinstance(email_body, bytes):
                email_message = email.message_from_bytes(email_body)
            else:
                email_message = email.message_from_string(str(email_body))

            raw_subject = email_message["Subject"]
            decoded_parts = decode_header(raw_subject)
            subject_parts = []
            for content, encoding in decoded_parts:
                if isinstance(content, bytes):
                    if encoding:
                        try:
                            subject_parts.append(content.decode(encoding))
                        except Exception:
                            subject_parts.append(
                                content.decode("utf-8", errors="ignore")
                            )
                    else:
                        subject_parts.append(content.decode("utf-8", errors="ignore"))
                else:
                    subject_parts.append(str(content))
            return "".join(subject_parts)
        except Exception:
            return ""

    def process_amazon_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            if "Ordered" not in subject and "ordered" not in subject.lower():
                logger.debug(f"Skipping non-confirmation Amazon email: {subject[:50]}")
                return {}

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                logger.warning("No HTML content found in Amazon confirmation email")
                return {}

            result = self.amazon_parser.parse_confirmation_email(html_content, subject)
            if not result.get("order_number"):
                logger.warning("Could not extract Amazon order number")
                return {}

            return {
                "date": email_date,
                "order_number": result["order_number"],
                "products": result.get("products", []),
                "total_price": result.get("total_price", "N/A"),
                "email_address": email_address,
                "state": result.get("state", ""),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Amazon confirmation email: {str(e)}")
            return {}

    def process_amazon_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            if "cancel" not in subject.lower():
                logger.debug(f"Skipping non-cancellation Amazon email: {subject[:50]}")
                return {}

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            result = self.amazon_parser.parse_cancellation_email(html_content, subject)
            if not result.get("order_number"):
                return {}

            return {
                "date": email_date,
                "order_number": result["order_number"],
                "email_address": email_address,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Amazon cancellation email: {str(e)}")
            return {}

    def process_amazon_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            result = self.amazon_parser.parse_shipped_email(html_content, subject)
            if not result.get("order_number"):
                return {}

            return {
                "date": email_date,
                "order_number": result["order_number"],
                "tracking_numbers": result.get("tracking_numbers", []),
                "tracking_with_links": result.get("tracking_with_links", []),
                "email_address": email_address,
                "state": result.get("state", ""),
                "track_package_link": result.get("track_package_link", ""),
                "products": result.get("products", []),
                "total_price": result.get("total_price", "N/A"),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Amazon shipped email: {str(e)}")
            return {}

    def process_walmart_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        if not self.walmart_parser:
            logger.warning("Walmart parser is not available")
            return {}
        try:
            subject = self._extract_subject(email_data)

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                logger.warning("No HTML content found in Walmart confirmation email")
                return {}

            if not self.walmart_parser.is_walmart_email(html_content):
                logger.debug("Skipping non-Walmart email")
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.walmart_parser.extract_order_number(
                soup, "confirmation", subject
            )
            if not order_number:
                logger.warning("Could not extract Walmart order number")
                return {}

            order_date = self.walmart_parser.extract_order_date(soup)
            products, total_price = self.walmart_parser.parse_product_details(
                html_content, subject
            )
            shipping_address = self.walmart_parser.extract_shipping_address(soup)

            return {
                "date": order_date or email_date,
                "order_number": order_number,
                "products": products,
                "total_price": total_price,
                "email_address": email_address,
                "state": shipping_address.get("state", ""),
                "zip": shipping_address.get("zip", ""),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Walmart confirmation email: {str(e)}")
            return {}

    def process_walmart_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        if not self.walmart_parser:
            logger.warning("Walmart parser is not available")
            return {}
        try:
            subject = self._extract_subject(email_data)

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            if not self.walmart_parser.is_walmart_email(html_content):
                logger.debug("Skipping non-Walmart email")
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.walmart_parser.extract_order_number(
                soup, "cancellation", subject
            )
            if not order_number:
                return {}

            return {
                "date": email_date,
                "order_number": order_number,
                "email_address": email_address,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Walmart cancellation email: {str(e)}")
            return {}

    def process_walmart_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        if not self.walmart_parser:
            logger.warning("Walmart parser is not available")
            return {}
        try:
            subject = self._extract_subject(email_data)

            email_address, email_date, html_content = self._parse_email_metadata(
                email_data
            )
            if not html_content:
                return {}

            if not self.walmart_parser.is_walmart_email(html_content):
                logger.debug("Skipping non-Walmart email")
                return {}

            soup = BeautifulSoup(html_content, "lxml")

            order_number = self.walmart_parser.extract_order_number(
                soup, "shipped", subject
            )
            if not order_number:
                return {}

            tracking_numbers = self.walmart_parser.extract_tracking_numbers(
                soup, html_content
            )
            shipping_address = self.walmart_parser.extract_shipping_address(soup)
            products, total_price = self.walmart_parser.parse_product_details(
                html_content, subject
            )

            return {
                "date": email_date,
                "order_number": order_number,
                "tracking_numbers": tracking_numbers,
                "products": products,
                "total_price": total_price,
                "state": shipping_address.get("state", ""),
                "zip": shipping_address.get("zip", ""),
                "email_address": email_address,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Error processing Walmart shipped email: {str(e)}")
            return {}
