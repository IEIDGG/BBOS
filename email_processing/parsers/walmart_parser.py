import re
import logging
from bs4 import BeautifulSoup
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)


class WalmartParser:

    @staticmethod
    def is_walmart_email(html_content: str) -> bool:
        return 'walmart.com' in html_content.lower() or 'walmartimages.com' in html_content.lower()

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return text
        text = text.replace('\u200c', '')
        text = text.replace('\u200b', '')
        text = text.replace('\xa0', ' ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _normalize_price(price: str) -> str:
        if not price:
            return price
        price = price.replace(' ', '')
        if not price.startswith('$'):
            price = '$' + price
        return price

    @staticmethod
    def _is_valid_walmart_order_number(text: str) -> bool:
        if not text:
            return False
        cleaned = text.lstrip('#').strip()
        return bool(re.match(r'^\d{7}-\d{7,10}$', cleaned))

    @staticmethod
    def extract_order_number(soup: BeautifulSoup, email_type: str, subject: str = None) -> Optional[str]:
        # Strategy 1: Find "Order number:" label followed by the order number
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            match = re.search(r'Order\s*number\s*:?\s*#?(\d{7}-\d{7,10})', text)
            if match:
                order_num = match.group(1)
                logger.debug(f"Extracted Walmart order number from TD: {order_num}")
                return order_num

        # Strategy 2: Find links containing order number pattern
        for a in soup.find_all('a'):
            text = a.get_text(strip=True).lstrip('#')
            if WalmartParser._is_valid_walmart_order_number(text):
                logger.debug(f"Extracted Walmart order number from link: {text}")
                return text

        # Strategy 3: Regex search in full text
        page_text = soup.get_text()
        match = re.search(r'(\d{7}-\d{7,10})', page_text)
        if match:
            logger.debug(f"Extracted Walmart order number from page text: {match.group(1)}")
            return match.group(1)

        return None

    @staticmethod
    def extract_order_date(soup: BeautifulSoup) -> Optional[str]:
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            match = re.search(r'Order\s*date\s*:\s*([\w,\s]+\d{4})', text)
            if match:
                date_str = match.group(1).strip()
                # Parse "Thu, Mar 19, 2026" or "Tue, Feb 17, 2026"
                try:
                    from datetime import datetime
                    # Try with day-of-week prefix
                    for fmt in ['%a, %b %d, %Y', '%b %d, %Y', '%A, %B %d, %Y']:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return dt.strftime('%Y-%m-%d')
                        except ValueError:
                            continue
                except Exception:
                    pass
                return date_str
        return None

    @staticmethod
    def parse_product_details(html_content: str, subject: str = None) -> Tuple[List[Dict[str, str]], str]:
        soup = BeautifulSoup(html_content, 'lxml')
        products = []

        # Primary: extract from img alt="quantity N item PRODUCT_NAME"
        for img in soup.find_all('img', alt=True):
            alt = img.get('alt', '')
            match = re.match(r'quantity\s+(\d+)\s+item\s+(.+)', alt, re.IGNORECASE)
            if match:
                qty = match.group(1)
                title = WalmartParser._clean_text(match.group(2))
                if title and not any(p['title'] == title for p in products):
                    products.append({
                        'title': title,
                        'quantity': qty,
                        'price': ''
                    })

        # Fallback: extract from subject line
        if not products and subject:
            cleaned_subject = re.sub(r'^(?:Fwd:\s*)?(?:Shipped|Canceled|Cancelled|Delivered):\s*', '', subject, flags=re.IGNORECASE).strip()
            cleaned_subject = re.sub(r'^delivery of\s+', '', cleaned_subject, flags=re.IGNORECASE).strip()
            cleaned_subject = re.sub(r'\s*[\U0001f300-\U0001f9ff\U0001fa00-\U0001faff]+\s*$', '', cleaned_subject).strip()
            if cleaned_subject and len(cleaned_subject) > 5:
                products.append({
                    'title': cleaned_subject,
                    'quantity': '1',
                    'price': ''
                })

        total_price = WalmartParser._extract_total_price(soup)

        return products, total_price

    @staticmethod
    def _extract_total_price(soup: BeautifulSoup) -> str:
        # Look for "Order total" section
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            match = re.search(r'Order\s*total.*?\$\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
            if match:
                return WalmartParser._normalize_price('$' + match.group(1))

        # Fallback: look for price patterns near "total" text
        page_text = soup.get_text()
        match = re.search(r'Order\s*total[^$]*\$([\d,]+\.?\d*)', page_text, re.IGNORECASE)
        if match:
            return WalmartParser._normalize_price('$' + match.group(1))

        return 'N/A'

    @staticmethod
    def extract_tracking_numbers(soup: BeautifulSoup, html_content: str = None) -> List[str]:
        tracking_numbers = []

        # Strategy 1: Find tracking number links inside TDs with carrier label text
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            if re.search(r'(?:Fedex|FedEx|UPS|USPS|OnTrac|DHL)\s+tracking\s+number', text, re.IGNORECASE):
                for a in td.find_all('a'):
                    link_text = a.get_text(strip=True).upper()
                    if re.match(r'^[A-Z0-9]{10,30}$', link_text) and link_text not in tracking_numbers:
                        tracking_numbers.append(link_text)
                        logger.info(f"Extracted Walmart tracking from carrier label: {link_text}")

        # Strategy 2: Find tracking number links near "tracking number" text
        if not tracking_numbers:
            for td in soup.find_all('td'):
                text = td.get_text(strip=True)
                if 'tracking number' in text.lower():
                    for a in td.find_all('a'):
                        link_text = a.get_text(strip=True).upper()
                        if re.match(r'^[A-Z0-9]{10,30}$', link_text) and link_text not in tracking_numbers:
                            tracking_numbers.append(link_text)
                            logger.info(f"Extracted Walmart tracking from link: {link_text}")

        # Strategy 3: Regex fallback on HTML content
        if not tracking_numbers and html_content:
            # UPS
            for m in re.findall(r'1Z[A-Z0-9]{16}', html_content):
                if m.upper() not in tracking_numbers:
                    tracking_numbers.append(m.upper())
            # FedEx (12 or 15 digits)
            for m in re.findall(r'\b(\d{12})\b', html_content):
                if m not in tracking_numbers:
                    tracking_numbers.append(m)
            for m in re.findall(r'\b(\d{15})\b', html_content):
                if m not in tracking_numbers:
                    tracking_numbers.append(m)
            # USPS
            for m in re.findall(r'(94\d{20,22})', html_content):
                if m not in tracking_numbers:
                    tracking_numbers.append(m)

        logger.info(f"Walmart tracking numbers found: {len(tracking_numbers)}")
        return tracking_numbers

    @staticmethod
    def extract_shipping_address(soup: BeautifulSoup) -> Dict[str, str]:
        address = {
            'name': '',
            'address1': '',
            'city': '',
            'state': '',
            'zip': ''
        }

        # Walmart emails include a Google Maps link with the full address
        for a in soup.find_all('a', href=lambda h: h and 'google.com/maps' in h):
            addr_text = WalmartParser._clean_text(a.get_text())
            if addr_text:
                # Parse "14143E SW Solange St, Apt 19, Port St Lucie, FL, 34987, USA"
                # or "Oakwater Dr, Apt t, Royal Palm Beach, FL, 33411, USA"
                match = re.search(r'(.+),\s*([A-Z]{2}),\s*(\d{5}(?:-\d{4})?)', addr_text)
                if match:
                    address_part = match.group(1).strip()
                    address['state'] = match.group(2)
                    address['zip'] = match.group(3)

                    # Split address part into street and city
                    parts = [p.strip() for p in address_part.split(',')]
                    if len(parts) >= 2:
                        address['city'] = parts[-1]
                        address['address1'] = ', '.join(parts[:-1])
                    else:
                        address['address1'] = address_part

                logger.debug(f"Extracted Walmart shipping address: {address}")
                break

        return address
