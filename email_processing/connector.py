"""
Email connection handler for the Best Buy Order Tracker application.
"""

import imaplib
import ssl
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

    def search_emails(self, folder: str, search_criteria: str) -> Tuple[bool, list]:
        """
        Search for emails in specified folder using given criteria.

        Args:
            folder: Email folder to search in
            search_criteria: IMAP search criteria

        Returns:
            Tuple of (success boolean, list of message IDs)
        """
        try:
            self.connection.select(folder)
            _, message_numbers = self.connection.search(None, search_criteria)
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