import email
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, Tuple
from .parsers.bb_parser import OrderParser
from .parsers.xbox_parser import XboxParser


class EmailProcessor:
    def __init__(self):
        self.order_parser = OrderParser()
        self.xbox_parser = XboxParser()

    def _parse_email_metadata(self, email_data: tuple) -> Tuple[str, str, Optional[str]]:
        if isinstance(email_data, tuple):
            email_body = email_data[1]
        else:
            email_body = email_data

        if isinstance(email_body, bytes):
            email_message = email.message_from_bytes(email_body)
        else:
            email_message = email.message_from_string(str(email_body))

        email_address = email_message['To']

        date_tuple = email.utils.parsedate_tz(email_message['Date'])
        if date_tuple:
            email_date = datetime.fromtimestamp(
                email.utils.mktime_tz(date_tuple)
            ).strftime("%Y-%m-%d")
        else:
            email_date = "Unknown"

        html_content = None
        for part in email_message.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    try:
                        html_content = payload.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            html_content = payload.decode('latin-1')
                        except UnicodeDecodeError:
                            print(f"Warning: Could not decode email content")
                            continue
                elif payload is not None:
                    html_content = str(payload)
                break

        return email_address, email_date, html_content

    def process_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                print("Warning: No HTML content found in email")
                return {}

            soup = BeautifulSoup(html_content, 'html.parser')
            order_number = self.order_parser.extract_order_number(soup, 'confirmation')
            if not order_number:
                print("Warning: Could not extract order number")
                return {}

            products, total_price = self.order_parser.parse_product_details(html_content)

            return {
                'date': email_date,
                'order_number': order_number,
                'products': products,
                'total_price': total_price,
                'email_address': email_address
            }
        except Exception as e:
            print(f"Error processing confirmation email: {str(e)}")
            return {}

    def process_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, 'html.parser')
            order_number = self.order_parser.extract_order_number(soup, 'cancelled')

            return {
                'date': email_date,
                'order_number': order_number
            }
        except Exception as e:
            print(f"Error processing cancellation email: {str(e)}")
            return {}

    def process_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, 'html.parser')
            order_number = self.order_parser.extract_order_number(soup, 'shipped')
            if not order_number:
                return {}

            tracking_numbers = self.order_parser.extract_tracking_numbers(soup)

            return {
                'date': email_date,
                'order_number': order_number,
                'tracking_numbers': tracking_numbers
            }
        except Exception as e:
            print(f"Error processing shipped email: {str(e)}")
            return {}

    def process_xbox_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            result = self.xbox_parser.extract_xbox_code(html_content)
            if not result:
                return {}

            result['date'] = email_date
            return result
        except Exception as e:
            print(f"Error processing Xbox email: {str(e)}")
            return {}