"""Pure HTML parsers for Apple Online Store order emails."""

import re
from datetime import datetime
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, FeatureNotFound


class AppleParser:
    """Extract normalized order details from Apple email HTML."""

    _ORDER_NUMBER_RE = re.compile(r"\bW\d{8,12}\b")
    _LOCATION_RE = re.compile(
        r"(?P<city>[A-Za-z][A-Za-z .'-]*?)\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)\b"
    )
    _PRICE_RE = re.compile(r"\$[\d,]+\.\d{2}")
    _CONFIRMATION_MARKERS = ("we're processing your order", "thank you for your order")

    def parse_confirmation(
        self, html_content: str, *, subject: str, email_address: str, email_date: str
    ) -> dict:
        normalized_subject = self._clean_text(subject).lower().replace("’", "'")
        if not any(
            marker in normalized_subject for marker in self._CONFIRMATION_MARKERS
        ):
            return {}
        soup = self._soup(html_content)
        order_number = self._order_number(soup, subject)
        if not order_number:
            return {}
        body = self._clean_text(soup.get_text(" ")).lower().replace("’", "'")
        if not (
            any(marker in body for marker in self._CONFIRMATION_MARKERS)
            or self._products(soup)
            or self._ordered_date(soup)
            or self._PRICE_RE.fullmatch(self._total(soup))
        ):
            return {}
        return self._order(
            soup,
            order_number=order_number,
            email_address=email_address,
            email_date=email_date,
        )

    def parse_cancellation(
        self, html_content: str, *, subject: str, email_address: str, email_date: str
    ) -> dict:
        soup = self._soup(html_content)
        if not re.search(
            r"\byour order has been cancel{1,2}ed\b",
            self._clean_text(soup.get_text(" ")).lower(),
        ):
            return {}
        order_number = self._order_number(soup, subject)
        if not order_number:
            return {}
        result = self._order(
            soup,
            order_number=order_number,
            email_address=email_address,
            email_date=email_date,
        )
        result["cancellation_type"] = "cancelled"
        return result

    def parse_shipment(
        self, html_content: str, *, subject: str, email_address: str, email_date: str
    ) -> dict:
        soup = self._soup(html_content)
        order_number = self._order_number(soup, subject)
        if not order_number:
            return {}
        result = self._order(
            soup,
            order_number=order_number,
            email_address=email_address,
            email_date=email_date,
        )
        result["tracking_numbers"] = self._tracking_numbers(soup, order_number)
        result["carrier"] = self._row_value(soup, "Carrier Name")
        if not (
            result["tracking_numbers"]
            or result["carrier"]
            or result["estimated_delivery"]
            or "your shipment is on its way"
            in self._clean_text(soup.get_text(" ")).lower()
        ):
            return {}
        return result

    @staticmethod
    def _soup(html_content: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html_content or "", "lxml")
        except FeatureNotFound:
            return BeautifulSoup(html_content or "", "html.parser")

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def _order_number(self, soup: BeautifulSoup, subject: str) -> str:
        for value in (subject, soup.get_text(" ")):
            match = self._ORDER_NUMBER_RE.search(value or "")
            if match:
                return match.group(0)
        return ""

    def _order(
        self,
        soup: BeautifulSoup,
        *,
        order_number: str,
        email_address: str,
        email_date: str,
    ) -> dict:
        location = self._location(soup)
        return {
            "order_number": order_number,
            "date": self._ordered_date(soup) or email_date,
            "products": self._products(soup),
            "total_price": self._total(soup),
            "estimated_delivery": self._delivery(soup),
            "email_address": email_address,
            "order_details_link": self._order_link(soup, order_number),
            "shipping_city": location["shipping_city"],
            "state": location["state"],
            "zip": location["zip"],
            "zip_and_state": location["zip_and_state"],
        }

    def _ordered_date(self, soup: BeautifulSoup) -> str:
        value = self._row_value(soup, "Ordered on")
        for date_format in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, date_format).date().isoformat()
            except ValueError:
                pass
        return ""

    def _products(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        products = []
        for table in soup.find_all("table"):
            classes = " ".join(table.get("class", [])).lower()
            if "item" not in classes and "shipment" not in classes:
                continue
            for quantity_cell in table.find_all(
                ["td", "th"], string=lambda text: self._clean_text(text) == "Qty"
            ):
                quantity = self._next_cell_text(quantity_cell)
                quantity_row = quantity_cell.find_parent("tr")
                if not quantity_row:
                    continue
                title_row = quantity_row.find_previous_sibling("tr")
                if not title_row:
                    continue
                cells = title_row.find_all(["td", "th"])
                values = [self._clean_text(cell.get_text(" ")) for cell in cells]
                title = next(
                    (
                        value
                        for value in values
                        if value and not self._PRICE_RE.fullmatch(value)
                    ),
                    "",
                )
                price = next(
                    (
                        match.group(0)
                        for value in values
                        if (match := self._PRICE_RE.search(value))
                    ),
                    "",
                )
                if title:
                    products.append(
                        {"title": title, "quantity": quantity or "1", "price": price}
                    )
        return products

    def _total(self, soup: BeautifulSoup) -> str:
        return self._row_value(soup, "Order Total")

    def _delivery(self, soup: BeautifulSoup) -> str:
        for cell in soup.find_all(["td", "th"]):
            text = self._clean_text(cell.get_text(" "))
            if not text.startswith("Delivers"):
                continue
            delivery = self._clean_text(text.removeprefix("Delivers"))
            return re.sub(r"\s+via\s+.+$", "", delivery, flags=re.IGNORECASE)
        return ""

    def _row_value(self, soup: BeautifulSoup, label: str) -> str:
        for cell in soup.find_all(["td", "th"]):
            if (
                self._clean_text(cell.get_text(" ")).rstrip(":").strip().casefold()
                == label.casefold()
            ):
                return self._next_cell_text(cell)
        return ""

    def _next_cell_text(self, cell) -> str:
        sibling = cell.find_next_sibling(["td", "th"])
        return self._clean_text(sibling.get_text(" ")) if sibling else ""

    def _order_link(self, soup: BeautifulSoup, order_number: str) -> str:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if re.search(r"[\s\\]", href):
                continue
            try:
                url = urlsplit(href)
                valid_origin = (
                    url.scheme == "https"
                    and url.hostname in {"store.apple.com", "secure.store.apple.com"}
                    and url.port in {None, 443}
                    and url.username is None
                    and url.password is None
                )
            except ValueError:
                continue
            if any(
                unquote(segment) in {".", ".."}
                or re.search(r"[/\\\s]", unquote(segment))
                for segment in url.path.split("/")
            ):
                continue
            if valid_origin and re.fullmatch(
                r"/(?:[a-z]{2}/|xc/[a-z]{2}/)?vieworder/"
                + re.escape(order_number)
                + r"(?:/[^/.][^/]*)?/?",
                url.path,
            ):
                return href
        return ""

    def _location(self, soup: BeautifulSoup) -> dict[str, str]:
        empty = {"shipping_city": "", "state": "", "zip": "", "zip_and_state": ""}
        blocks = []
        # Labeled address cells take precedence over template-specific blocks.
        for cell in soup.find_all(["td", "th"]):
            cell_text = self._clean_text(cell.get_text(" "))
            label = cell_text.rstrip(":").casefold()
            same_cell_heading = re.match(
                r"^(?:shipping address|ship to)\s*:", cell_text, re.I
            )
            if same_cell_heading and cell_text[same_cell_heading.end() :].strip():
                blocks.append(cell)
                continue
            if label in {"shipping address", "ship to"}:
                address_cell = cell.find_next_sibling(["td", "th"])
                if address_cell is not None:
                    blocks.append(address_cell)
                else:
                    row = cell.find_parent("tr")
                    next_row = row.find_next_sibling("tr") if row else None
                    if next_row is not None:
                        blocks.append(next_row)
        if not blocks:
            blocks = soup.select("table.fulfillment, table.shipment-content")
        address = ""
        for block in blocks:
            match = self._LOCATION_RE.search(block.get_text("\n"))
            if match:
                address = match.group(0)
                break
        if not address:
            return empty
        try:
            from services.location import copy_location_fields, parse_location

            parsed = copy_location_fields(parse_location(address))
            return {**empty, **parsed}
        except ImportError:
            match = list(self._LOCATION_RE.finditer(address))[-1]
            city = self._clean_text(match.group("city"))
            state = match.group("state")
            zip_code = match.group("zip")
            return {
                "shipping_city": city,
                "state": state,
                "zip": zip_code,
                "zip_and_state": f"{city}, {state} {zip_code}",
            }

    def _tracking_numbers(self, soup: BeautifulSoup, order_number: str) -> list[str]:
        tracking_numbers = []
        for label in soup.find_all(["td", "th"]):
            if self._clean_text(label.get_text(" ")).lower() != "tracking number:":
                continue
            value_cell = label.find_next_sibling(["td", "th"])
            if not value_cell:
                continue
            for value in value_cell.stripped_strings:
                candidate = self._clean_text(value)
                if (
                    self._valid_tracking(candidate, order_number)
                    and candidate not in tracking_numbers
                ):
                    tracking_numbers.append(candidate)
        return tracking_numbers

    @staticmethod
    def _valid_tracking(value: str, order_number: str) -> bool:
        compact = re.sub(r"\s+", "", value)
        return (
            compact != order_number
            and not re.search(r"[•*xX]{3,}", compact)
            and not re.fullmatch(r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}", compact)
            and bool(re.fullmatch(r"[A-Za-z0-9]{8,35}", compact))
        )
