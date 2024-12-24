"""
Utility functions for the Best Buy Order Tracker application.
"""

from typing import Tuple, Dict
import os
from datetime import datetime


def read_credentials(filename: str) -> Tuple[str, str, str]:
    """
    Read credentials from file.

    Args:
        filename: Path to credentials file

    Returns:
        Tuple of (email, password, service_type)
    """
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise ValueError("Credentials file must contain at least email and password")

            email = lines[0].split('=')[1].strip()
            password = lines[1].split('=')[1].strip()

            # Default to gmail if service type not specified
            service_type = (
                lines[2].split('=')[1].strip().lower()
                if len(lines) > 2
                else 'gmail'
            )

            # Validate service type
            if service_type not in ['gmail', 'proton', 'icloud']:
                service_type = 'gmail'

            return email, password, service_type
    except Exception as e:
        print(f"Error reading credentials file: {str(e)}")
        raise


def setup_logging(log_dir: str = 'logs') -> str:
    """
    Set up logging directory and return log filename.

    Args:
        log_dir: Directory to store log files

    Returns:
        Path to log file
    """
    try:
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.join(log_dir, f'bestbuy_tracker_{timestamp}.log')
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        return ''


def validate_email_service(service: str) -> str:
    """
    Validate and normalize email service type.

    Args:
        service: Email service type to validate

    Returns:
        Normalized service type string
    """
    valid_services = {'gmail', 'proton', 'icloud'}
    service = service.lower().strip()
    return service if service in valid_services else 'gmail'


def format_order_details(order: Dict) -> str:
    """
    Format order details for display.

    Args:
        order: Order dictionary containing details

    Returns:
        Formatted string of order details
    """
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
    """
    Clean filename by removing invalid characters.

    Args:
        filename: Original filename

    Returns:
        Cleaned filename
    """
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


def parse_date_string(date_str: str) -> datetime:
    """
    Parse date string into datetime object.

    Args:
        date_str: Date string to parse

    Returns:
        Datetime object
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        try:
            return datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            raise ValueError(f"Unable to parse date string: {date_str}")


def format_currency(amount: str) -> str:
    """
    Format currency string consistently.

    Args:
        amount: Currency amount string

    Returns:
        Formatted currency string
    """
    try:
        # Remove currency symbol and extra spaces
        amount = amount.replace('$', '').strip()
        # Convert to float and format
        value = float(amount.replace(',', ''))
        return f"${value:,.2f}"
    except ValueError:
        return amount  # Return original if parsing fails