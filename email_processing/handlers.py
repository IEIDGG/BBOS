from typing import List, Dict, Tuple
from datetime import datetime
import email
from .connector import EmailConnector
from .processor import EmailProcessor
from config.settings import SEARCH_CRITERIA


class BaseEmailHandler:
    def __init__(self, connector: EmailConnector):
        self.connector = connector
        self.processor = EmailProcessor()
        self.statistics = {
            'processed': 0,
            'successful': 0,
            'failed': 0
        }

    def _update_stats(self, success: bool) -> None:
        self.statistics['processed'] += 1
        if success:
            self.statistics['successful'] += 1
        else:
            self.statistics['failed'] += 1


class OrderEmailHandler(BaseEmailHandler):
    def __init__(self, connector: EmailConnector):
        super().__init__(connector)
        self.statistics.update({
            'confirmations': 0,
            'cancellations': 0,
            'shipped': 0,
            'tracking_numbers': 0
        })

    def process_confirmation_emails(self, folder: str) -> List[Dict]:
        print(f"\nProcessing confirmation emails in folder: {folder}")

        success, messages = self.connector.search_emails(folder, SEARCH_CRITERIA['confirmation'])

        if not success:
            return []

        print(f"Found {len(messages)} confirmation emails")
        orders = []

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_confirmation_email(email_data)
            if result.get('order_number'):
                orders.append({
                    'date': result['date'],
                    'number': result['order_number'],
                    'status': "",
                    'tracking': [],
                    'products': result['products'],
                    'total_price': result['total_price'],
                    'email_address': result['email_address']
                })
                self.statistics['confirmations'] += 1
                print(f"Processed confirmation: Order {result['order_number']}")

            self._update_stats(bool(result.get('order_number')))

        return orders

    def process_cancellation_emails(self, folder: str, orders: List[Dict]) -> None:
        print(f"\nProcessing cancellation emails in folder: {folder}")

        success, messages = self.connector.search_emails(
            folder,
            SEARCH_CRITERIA['cancellation']
        )

        if not success:
            return

        print(f"Found {len(messages)} cancellation emails")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_cancellation_email(email_data)
            if result.get('order_number'):
                for order in orders:
                    if order['number'] == result['order_number']:
                        order['status'] = "Cancelled"
                        self.statistics['cancellations'] += 1
                        print(f"Processed cancellation: Order {result['order_number']}")
                        break

            self._update_stats(bool(result.get('order_number')))

    def process_shipped_emails(self, folder: str, orders: List[Dict]) -> None:
        print(f"\nProcessing shipped emails in folder: {folder}")

        success, messages = self.connector.search_emails(
            folder,
            SEARCH_CRITERIA['shipped']
        )

        if not success:
            return

        print(f"Found {len(messages)} shipped emails")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_shipped_email(email_data)
            if result.get('order_number'):
                for order in orders:
                    if order['number'] == result['order_number']:
                        order['status'] = "Shipped"
                        order['tracking'] = result['tracking_numbers']
                        self.statistics['shipped'] += 1
                        self.statistics['tracking_numbers'] += len(result['tracking_numbers'])
                        print(f"Processed shipped: Order {result['order_number']}")
                        break

            self._update_stats(bool(result.get('order_number')))

    def get_statistics(self) -> Dict:
        return self.statistics


class XboxEmailHandler(BaseEmailHandler):
    def process_xbox_emails(self, folder: str) -> List[Dict]:
        print(f"\nProcessing Xbox Game Pass emails in folder: {folder}")

        success, messages = self.connector.search_emails(folder, SEARCH_CRITERIA['xbox'])

        if not success:
            print("Failed to search for Xbox Game Pass emails")
            return []

        if not messages:
            print("No Xbox Game Pass emails found")
            return []

        print(f"Found {len(messages)} Xbox Game Pass emails")
        xbox_codes = []

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success or not email_data:
                print(f"Failed to fetch email ID: {msg_id}")
                continue

            result = self.processor.process_xbox_email(email_data)
            if result.get('code'):
                xbox_codes.append(result)
                print(f"Processed Xbox code: {result['code']}")
            else:
                print(f"No Xbox code found in email ID: {msg_id}")

            self._update_stats(bool(result.get('code')))

        return xbox_codes