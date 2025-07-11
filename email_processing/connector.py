import imaplib
import ssl
import re
import time
from datetime import datetime
from typing import Optional, Tuple
from config.settings import EMAIL_SERVERS


class EmailConnector:
    def __init__(self, email: str, password: str, service_type: str):
        self.email = email
        self.password = password
        self.service_config = EMAIL_SERVERS.get(service_type, EMAIL_SERVERS['gmail'])
        self.connection: Optional[imaplib.IMAP4] = None

    def connect(self) -> None:
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
        formatted_parts = []

        if 'date' in criteria_parts:
            imap_date = self._format_date_for_imap(criteria_parts['date'])
            if imap_date:
                formatted_parts.append(f'SINCE {imap_date}')

        if 'from' in criteria_parts:
            from_criteria = criteria_parts['from']
            if '(OR' in from_criteria:
                addresses = re.findall(r'"([^"]+)"', from_criteria)
                if addresses:
                    if len(addresses) == 2:
                        formatted_parts.append(f'OR (FROM "{addresses[0]}") (FROM "{addresses[1]}")')
                    else:
                        or_conditions = ' '.join(f'(FROM "{addr}")' for addr in addresses)
                        formatted_parts.append(f'OR {or_conditions}')
            else:
                address = re.search(r'"([^"]+)"', from_criteria)
                if address:
                    formatted_parts.append(f'FROM "{address.group(1)}"')

        if 'subject' in criteria_parts:
            subject_criteria = criteria_parts['subject']
            if 'OR' in subject_criteria:
                subjects = re.findall(r'"([^"]+)"', subject_criteria)
                if subjects:
                    subjects_formatted = ' '.join(f'(SUBJECT "{subject}")' for subject in subjects)
                    formatted_parts.append(f'OR {subjects_formatted}')
            else:
                subject = re.search(r'"([^"]+)"', subject_criteria)
                if subject:
                    formatted_parts.append(f'SUBJECT "{subject.group(1)}"')

        return ' '.join(formatted_parts)

    def _reconnect(self) -> bool:
        try:
            print("Attempting to reconnect...")
            if self.connection:
                try:
                    self.connection.logout()
                except:
                    pass
            self.connect()
            return True
        except Exception as e:
            print(f"Reconnection failed: {str(e)}")
            return False

    def search_emails(self, folder: str, search_criteria: dict, max_retries: int = 3) -> Tuple[bool, list]:
        for attempt in range(max_retries):
            try:
                quoted_folder = f'"{folder}"' if ' ' in folder or '/' in folder else folder
                self.connection.select(quoted_folder)
                formatted_criteria = self._format_search_criteria(search_criteria)
                print(f"Using IMAP search criteria: {formatted_criteria}")
                _, message_numbers = self.connection.search(None, formatted_criteria)
                return True, message_numbers[0].split()
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
                print(f"Connection error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    if self._reconnect():
                        time.sleep(2)
                        continue
                    else:
                        time.sleep(5)
                return False, []
            except Exception as e:
                print(f"Error searching emails in {folder}: {str(e)}")
                return False, []
        return False, []

    def fetch_email(self, message_id: bytes, protocol: str = 'RFC822', max_retries: int = 3) -> Tuple[bool, Optional[tuple]]:
        for attempt in range(max_retries):
            try:
                fetch_protocol = 'BODY[]' if self.service_config['server'] == 'imap.mail.me.com' else protocol
                _, msg_data = self.connection.fetch(message_id, f'({fetch_protocol})')
                return True, msg_data[0]
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
                print(f"Connection error fetching email {message_id} on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    if self._reconnect():
                        time.sleep(1)
                        continue
                    else:
                        time.sleep(3)
                return False, None
            except Exception as e:
                print(f"Error fetching email {message_id}: {str(e)}")
                return False, None
        return False, None

    def get_folders(self) -> list:
        try:
            _, folders = self.connection.list()
            folder_names = []
            for folder in folders:
                folder_str = folder.decode()
                if '"' in folder_str:
                    parts = folder_str.split('"')
                    if len(parts) >= 3:
                        folder_names.append(parts[-2])
                else:
                    parts = folder_str.split(' ')
                    if len(parts) >= 3:
                        folder_names.append(' '.join(parts[2:]))
            return folder_names
        except Exception as e:
            print(f"Error getting folders: {str(e)}")
            return []

    def disconnect(self) -> None:
        if self.connection:
            try:
                self.connection.logout()
                print("Email connection closed successfully")
            except Exception as e:
                print(f"Error disconnecting: {str(e)}")
            finally:
                self.connection = None