"""
Parser for Best Buy order confirmation emails.
"""

from bs4 import BeautifulSoup
from typing import Tuple, List, Dict, Any


class OrderParser:
    @staticmethod
    def parse_product_details(html_content: str) -> Tuple[List[Dict[str, str]], str]:
        """Parse product details from order confirmation email HTML."""
        soup = BeautifulSoup(html_content, 'html.parser')
        products = []

        # Find product sections
        product_sections = soup.find_all(
            'td',
            style=lambda value: value and 'width:60%;max-width:359px;' in value
        )

        for section in product_sections:
            # Extract title
            title_tag = section.find('a', style='text-decoration: none;')
            if not title_tag:
                continue

            # Extract quantity
            qty_tag = section.find_next('td', string='Qty:')
            qty = qty_tag.find_next_sibling('td').text.strip() if qty_tag else "N/A"

            # Extract price
            price_tag = section.find(
                'span',
                string=lambda text: text and '$' in text,
                style=lambda value: value and 'font-weight: 700;font-size: 14px;line-height: 18px;' in value
            )
            price = price_tag.text.strip() if price_tag else "N/A"

            if price != "N/A":
                products.append({
                    'title': title_tag.text.strip(),
                    'quantity': qty,
                    'price': price
                })

        # Extract total price
        total_td = soup.find(
            'td',
            align='right',
            style=lambda
                value: value and 'padding-top:12px; padding-left:0;padding-right:0; padding-bottom:0; color:#000000;' in value
        )
        total_price = total_td.text.strip() if total_td else "N/A"

        return products, total_price

    @staticmethod
    def extract_order_number(soup: BeautifulSoup, email_type: str) -> str:
        """Extract order number based on email type."""
        if email_type == 'confirmation':
            order_span = soup.find('span', string=lambda text: text and 'BBY01-' in text)
            return order_span.text.strip() if order_span else None

        # For cancellation or shipped emails
        order_span = soup.find('span', style='font: bold 23px Arial; color: #1d252c;')
        if order_span:
            return order_span.text.strip().replace("Order #", "")

        # Alternative format
        order_tds = soup.find_all('td', style='padding-bottom:12px;')
        for td in order_tds:
            if 'Order number:' in td.text:
                order_span = td.find(
                    'span',
                    style=lambda value: value and 'font-weight: 700' in value and 'font-size: 14px' in value
                )
                if order_span:
                    return order_span.text.strip()

        return None

    @staticmethod
    def extract_tracking_numbers(soup: BeautifulSoup) -> List[str]:
        """Extract tracking numbers from shipped email."""
        tracking_numbers = []

        # First format
        tracking_spans = soup.find_all('span', style='font: bold 14px Arial')
        for span in tracking_spans:
            if 'Tracking #:' in span.text:
                tracking_link = span.find('a')
                if tracking_link:
                    tracking_numbers.append(tracking_link.text.strip())

        # Alternative format
        tracking_tds = soup.find_all('td', style='padding-bottom:12px;')
        for td in tracking_tds:
            if 'Tracking Number:' in td.text:
                tracking_span = td.find(
                    'span',
                    style=lambda value: value and 'font-weight: 700' in value and 'font-size: 14px' in value
                )
                if tracking_span:
                    tracking_numbers.append(tracking_span.text.strip())

        return tracking_numbers