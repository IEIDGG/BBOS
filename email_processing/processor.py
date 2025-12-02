import email
import logging
from email.header import decode_header
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, Tuple
from .parsers.bb_parser import OrderParser
from .parsers.xbox_parser import XboxParser
from .parsers.costco_parser import CostcoParser
from .parsers.amazon_parser import AmazonParser

logger = logging.getLogger(__name__)


class EmailProcessor:
    def __init__(self):
        self.order_parser = OrderParser()
        self.xbox_parser = XboxParser()
        self.costco_parser = CostcoParser()
        self.amazon_parser = AmazonParser()

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
        
        raw_subject = email_message['Subject']
        decoded_parts = decode_header(raw_subject)
        subject_parts = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                if encoding:
                    try:
                        subject_parts.append(content.decode(encoding))
                    except:
                        subject_parts.append(content.decode('utf-8', errors='ignore'))
                else:
                    subject_parts.append(content.decode('utf-8', errors='ignore'))
            else:
                subject_parts.append(str(content))
        subject = ''.join(subject_parts)

        date_tuple = email.utils.parsedate_tz(email_message['Date'])
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
        
        print(f"  📧 Subject: {subject[:60]}{'...' if len(subject) > 60 else ''}")
        print(f"     Date: {email_date} | To: {email_address}")
        print(f"     Parts: {', '.join(set(content_types))} | HTML: {'✓' if html_content else '✗'}")

        return email_address, email_date, html_content

    def process_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                print("Warning: No HTML content found in email")
                return {}

            soup = BeautifulSoup(html_content, 'lxml')
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

            soup = BeautifulSoup(html_content, 'lxml')
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

            soup = BeautifulSoup(html_content, 'lxml')
            order_number = self.order_parser.extract_order_number(soup, 'shipped')
            if not order_number:
                return {}

            tracking_numbers = self.order_parser.extract_tracking_numbers(soup)
            address_info = self.order_parser.extract_shipping_address(soup)

            return {
                'date': email_date,
                'order_number': order_number,
                'tracking_numbers': tracking_numbers,
                'address_info': address_info
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

    def process_costco_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            if 'Confirmed' not in subject and 'confirmed' not in subject.lower():
                logger.debug(f"Skipping non-confirmation email: {subject[:50]}")
                return {}
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                logger.warning("No HTML content found in Costco confirmation email")
                return {}

            soup = BeautifulSoup(html_content, 'lxml')
            
            order_number = self.costco_parser.extract_order_number(soup, 'confirmation', subject)
            if not order_number:
                logger.warning("Could not extract Costco order number")
                return {}

            order_date = self.costco_parser.extract_order_date(soup)
            membership_number = self.costco_parser.extract_membership_number(soup)
            shipping_address = self.costco_parser.extract_shipping_address(soup)
            products, total_price = self.costco_parser.parse_product_details(html_content)
            price_summary = self.costco_parser.extract_price_summary(soup)

            return {
                'date': order_date or email_date,
                'order_number': order_number,
                'membership_number': membership_number,
                'shipping_address': shipping_address,
                'products': products,
                'total_price': total_price,
                'price_summary': price_summary,
                'email_address': email_address,
                'state': shipping_address.get('state', ''),
                'subject': subject
            }
        except Exception as e:
            logger.error(f"Error processing Costco confirmation email: {str(e)}")
            return {}

    def process_costco_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            if 'Cancelled' not in subject and 'cancelled' not in subject.lower() and 'Canceled' not in subject and 'canceled' not in subject.lower():
                logger.debug(f"Skipping non-cancellation email: {subject[:50]}")
                return {}
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, 'lxml')
            
            order_number = self.costco_parser.extract_order_number(soup, 'cancellation', subject)
            cancellation_date = self.costco_parser.extract_cancellation_date(soup)

            return {
                'date': email_date,
                'order_number': order_number,
                'cancellation_date': cancellation_date,
                'email_address': email_address,
                'subject': subject
            }
        except Exception as e:
            logger.error(f"Error processing Costco cancellation email: {str(e)}")
            return {}

    def process_costco_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            if 'Shipped' not in subject and 'shipped' not in subject.lower():
                logger.debug(f"Skipping non-shipped email: {subject[:50]}")
                return {}
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            soup = BeautifulSoup(html_content, 'lxml')
            
            order_number = self.costco_parser.extract_order_number(soup, 'shipped', subject)
            if not order_number:
                return {}

            tracking_numbers = self.costco_parser.extract_tracking_numbers(soup, html_content)

            return {
                'date': email_date,
                'order_number': order_number,
                'tracking_numbers': tracking_numbers,
                'email_address': email_address,
                'subject': subject
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

            raw_subject = email_message['Subject']
            decoded_parts = decode_header(raw_subject)
            subject_parts = []
            for content, encoding in decoded_parts:
                if isinstance(content, bytes):
                    if encoding:
                        try:
                            subject_parts.append(content.decode(encoding))
                        except:
                            subject_parts.append(content.decode('utf-8', errors='ignore'))
                    else:
                        subject_parts.append(content.decode('utf-8', errors='ignore'))
                else:
                    subject_parts.append(str(content))
            return ''.join(subject_parts)
        except Exception:
            return ''

    def process_amazon_confirmation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            if 'Ordered' not in subject and 'ordered' not in subject.lower():
                logger.debug(f"Skipping non-confirmation Amazon email: {subject[:50]}")
                return {}
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                logger.warning("No HTML content found in Amazon confirmation email")
                return {}

            result = self.amazon_parser.parse_confirmation_email(html_content, subject)
            if not result.get('order_number'):
                logger.warning("Could not extract Amazon order number")
                return {}

            return {
                'date': email_date,
                'order_number': result['order_number'],
                'products': result.get('products', []),
                'total_price': result.get('total_price', 'N/A'),
                'email_address': email_address,
                'state': result.get('state', ''),
                'subject': subject
            }
        except Exception as e:
            logger.error(f"Error processing Amazon confirmation email: {str(e)}")
            return {}

    def process_amazon_cancellation_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            if 'cancel' not in subject.lower():
                logger.debug(f"Skipping non-cancellation Amazon email: {subject[:50]}")
                return {}
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            result = self.amazon_parser.parse_cancellation_email(html_content, subject)
            if not result.get('order_number'):
                return {}

            return {
                'date': email_date,
                'order_number': result['order_number'],
                'email_address': email_address,
                'subject': subject
            }
        except Exception as e:
            logger.error(f"Error processing Amazon cancellation email: {str(e)}")
            return {}

    def process_amazon_shipped_email(self, email_data: tuple) -> Dict[str, Any]:
        try:
            subject = self._extract_subject(email_data)
            
            email_address, email_date, html_content = self._parse_email_metadata(email_data)
            if not html_content:
                return {}

            result = self.amazon_parser.parse_shipped_email(html_content, subject)
            if not result.get('order_number'):
                return {}

            return {
                'date': email_date,
                'order_number': result['order_number'],
                'tracking_numbers': result.get('tracking_numbers', []),
                'tracking_with_links': result.get('tracking_with_links', []),
                'email_address': email_address,
                'state': result.get('state', ''),
                'track_package_link': result.get('track_package_link', ''),
                'products': result.get('products', []),
                'total_price': result.get('total_price', 'N/A'),
                'subject': subject
            }
        except Exception as e:
            logger.error(f"Error processing Amazon shipped email: {str(e)}")
            return {}
