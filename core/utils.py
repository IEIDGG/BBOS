from typing import Tuple, Dict
import os
from datetime import datetime


def read_credentials(filename: str) -> Tuple[str, str, str]:
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise ValueError("Credentials file must contain at least email and password")

            email = lines[0].split('=')[1].strip()
            password = lines[1].split('=')[1].strip()

            service_type = (
                lines[2].split('=')[1].strip().lower()
                if len(lines) > 2
                else 'gmail'
            )

            if service_type not in ['gmail', 'proton', 'icloud']:
                service_type = 'gmail'

            return email, password, service_type
    except Exception as e:
        print(f"Error reading credentials file: {str(e)}")
        raise


def setup_logging(log_dir: str = 'logs', service: str = 'bestbuy') -> str:
    try:
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.join(log_dir, f'{service}_tracker_{timestamp}.log')
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        return ''


def validate_email_service(service: str) -> str:
    valid_services = {'gmail', 'proton', 'icloud'}
    service = service.lower().strip()
    return service if service in valid_services else 'gmail'


def format_order_details(order: Dict) -> str:
    details = [
        f"Order Number: {order['number']}",
        f"Date: {order['date']}",
        f"Status: {order['status'] or 'Processing'}",
        f"Total Price: {order['total_price']}",
        "\nProducts:"
    ]

    for product in order['products']:
        details.append(
            f"  - {product['title']} (Qty: {product['quantity']}, Price: {product['price']})"
        )

    if order['tracking']:
        details.append("\nTracking Numbers:")
        for tracking in order['tracking']:
            details.append(f"  - {tracking}")

    return '\n'.join(details)


def clean_filename(filename: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


def parse_date_string(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        try:
            return datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            raise ValueError(f"Unable to parse date string: {date_str}")


def format_currency(amount: str) -> str:
    try:
        amount = amount.replace('$', '').strip()
        value = float(amount.replace(',', ''))
        return f"${value:,.2f}"
    except ValueError:
        return amount


def get_db_settings(service: str = 'bestbuy') -> Dict:
    from config.settings import DB_SETTINGS, AMAZON_DB_SETTINGS
    
    if service.lower() == 'amazon':
        return AMAZON_DB_SETTINGS
    else:
        return DB_SETTINGS


def get_output_filename(service: str = 'bestbuy', file_type: str = 'csv') -> str:
    from config.settings import OUTPUT_SETTINGS
    
    if service.lower() == 'amazon':
        return f'amazon_orders.{file_type}'
    elif file_type == 'csv':
        return OUTPUT_SETTINGS['csv_filename']
    elif file_type == 'xbox':
        return OUTPUT_SETTINGS['xbox_filename']
    else:
        return f'{service}_orders.{file_type}'