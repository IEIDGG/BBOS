"""
Email connection handler for the Best Buy Order Tracker application.
"""

import imaplib
import ssl
import re
from datetime import datetime
from typing import Optional, Tuple
from config.settings import EMAIL_SERVERS


class EmailConnector:
    def __init__(self, email: str, password: str, service_type: str):
        """Initialize email connector with credentials and service type."""
        self.email = email
        self.password = password
        self.service_config = EMAIL_SERVERS.get(service_type, EMAIL_SERVERS['gmail'])
        self.connection: Optional[imaplib.IMAP4] = None

    def connect(self) -> None:
        """Establish connection to the email server."""
        try:
            if self.service_config['use_ssl']:
                self.connection = imaplib.IMAP4_SSL(
                    self.service_config['server'],
                    self.service_config['port']
                )
            else:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.connection = imaplib.IMAP4(
                    self.service_config['server'],
                    self.service_config['port']
                )
                self.connection.starttls(ssl_context=context)

            self.connection.login(self.email, self.password)
            print(f"Successfully connected to {self.service_config['server']}")
        except Exception as e:
            print(f"Error connecting to email server: {str(e)}")
            raise

    def _format_date_for_imap(self, date_str: str) -> str:
        """Convert date string to IMAP-compatible format."""
        if not date_str:
            return ""

        try:
            clean_date = date_str.replace('after:', '')
            date_obj = datetime.strptime(clean_date, '%Y/%m/%d')
            return date_obj.strftime('%d-%b-%Y')
        except ValueError as e:
            print(f"Error formatting date: {str(e)}")
            return ""

    def _format_search_criteria(self, criteria_parts: dict) -> str:
        """Format search criteria for IMAP."""
        formatted_parts = []

        # Handle date
        if 'date' in criteria_parts:
            imap_date = self._format_date_for_imap(criteria_parts['date'])
            if imap_date:
                formatted_parts.append(f'SINCE {imap_date}')

        # Handle from address
        if 'from' in criteria_parts:
            from_criteria = criteria_parts['from']
            if '(OR' in from_criteria:
                # Extract email addresses from the OR condition
                addresses = re.findall(r'"([^"]+)"', from_criteria)
                if addresses:
                    formatted_parts.append(f'OR (FROM "{addresses[0]}") (FROM "{addresses[1]}")')
            else:
                # Single from address
                address = re.search(r'"([^"]+)"', from_criteria)
                if address:
                    formatted_parts.append(f'FROM "{address.group(1)}"')

        # Handle subject
        if 'subject' in criteria_parts:
            subject_criteria = criteria_parts['subject']
            if 'OR' in subject_criteria:
                # Handle OR in subject
                subjects = re.findall(r'"([^"]+)"', subject_criteria)
                if subjects:
                    subjects_formatted = ' '.join(f'(SUBJECT "{subject}")' for subject in subjects)
                    formatted_parts.append(f'OR {subjects_formatted}')
            else:
                # Single subject
                subject = re.search(r'"([^"]+)"', subject_criteria)
                if subject:
                    formatted_parts.append(f'SUBJECT "{subject.group(1)}"')

        # Join all parts
        return ' '.join(formatted_parts)

    def search_emails(self, folder: str, search_criteria: dict) -> Tuple[bool, list]:
        """Search for emails in specified folder using given criteria."""
        try:
            self.connection.select(folder)
            formatted_criteria = self._format_search_criteria(search_criteria)
            print(f"Using IMAP search criteria: {formatted_criteria}")
            _, message_numbers = self.connection.search(None, formatted_criteria)
            return True, message_numbers[0].split()
        except Exception as e:
            print(f"Error searching emails in {folder}: {str(e)}")
            return False, []

    def fetch_email(self, message_id: bytes, protocol: str = 'RFC822') -> Tuple[bool, Optional[tuple]]:
        """
        Fetch a specific email message.

        Args:
            message_id: Email message ID
            protocol: IMAP protocol to use for fetching (defaults to RFC822)

        Returns:
            Tuple of (success boolean, message data)
        """
        try:
            # Use BODY[] for iCloud accounts, RFC822 for others
            fetch_protocol = 'BODY[]' if self.service_config['server'] == 'imap.mail.me.com' else protocol
            _, msg_data = self.connection.fetch(message_id, f'({fetch_protocol})')
            return True, msg_data[0]
        except Exception as e:
            print(f"Error fetching email {message_id}: {str(e)}")
            return False, None

    def get_folders(self) -> list:
        """Get list of available folders."""
        try:
            _, folders = self.connection.list()
            return [folder.decode().split('"')[-2] for folder in folders]
        except Exception as e:
            print(f"Error getting folders: {str(e)}")
            return []

    def disconnect(self) -> None:
        """Close the email connection."""
        if self.connection:
            try:
                self.connection.logout()
                print("Email connection closed successfully")
            except Exception as e:
                print(f"Error disconnecting: {str(e)}")
            finally:
                self.connection = None