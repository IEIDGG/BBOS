import imaplib
import ssl
import re
import time
from datetime import datetime
from typing import Optional, Tuple, List
from functools import wraps
from config.settings import EMAIL_SERVERS


def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay}s due to: {str(e)}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


class EmailConnector:
    def __init__(self, email: str, password: str, service_type: str):
        self.email = email
        self.password = password
        self.service_config = EMAIL_SERVERS.get(service_type, EMAIL_SERVERS['gmail'])
        self.connection: Optional[imaplib.IMAP4] = None
        self.fetch_count = 0
        self.max_fetches_per_session = 1000
        self.batch_size = 50
        self.fetch_delay = 0.1

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
                    if len(addresses) > 1:
                        or_chain = f'FROM "{addresses[0]}"'
                        for address in addresses[1:]:
                            or_chain = f'OR {or_chain} FROM "{address}"'
                        formatted_parts.append(f'({or_chain})')
                    else:
                        formatted_parts.append(f'FROM "{addresses[0]}"')
            else:
                address = re.search(r'"([^"]+)"', from_criteria)
                if address:
                    formatted_parts.append(f'FROM "{address.group(1)}"')

        if 'subject' in criteria_parts:
            subject_criteria = criteria_parts['subject']
            if 'OR' in subject_criteria:
                subjects = re.findall(r'"([^"]+)"', subject_criteria)
                if subjects:
                    if len(subjects) > 1:
                        or_chain = f'SUBJECT "{subjects[0]}"'
                        for subject in subjects[1:]:
                            or_chain = f'OR {or_chain} SUBJECT "{subject}"'
                        formatted_parts.append(f'({or_chain})')
                    else:
                        formatted_parts.append(f'SUBJECT "{subjects[0]}"')
            else:
                subject = re.search(r'"([^"]+)"', subject_criteria)
                if subject:
                    formatted_parts.append(f'SUBJECT "{subject.group(1)}"')

        return ' '.join(formatted_parts)

    def search_emails(self, folder: str, search_criteria: dict) -> Tuple[bool, list]:
        try:
            quoted_folder = f'"{folder}"' if ' ' in folder or '/' in folder else folder
            self.connection.select(quoted_folder)
            formatted_criteria = self._format_search_criteria(search_criteria)
            print(f"Using IMAP search criteria: {formatted_criteria}")
            _, message_numbers = self.connection.search(None, formatted_criteria)
            if message_numbers[0]:
                return True, message_numbers[0].split()
            return True, []
        except Exception as e:
            print(f"Error searching emails in {folder}: {str(e)}")
            return False, []

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_email(self, message_id: bytes, protocol: str = 'BODY.PEEK[]') -> Tuple[bool, Optional[tuple]]:
        try:
            if self.fetch_count >= self.max_fetches_per_session:
                print(f"Warning: Reached max fetches per session ({self.max_fetches_per_session})")
                return False, None
            
            fetch_protocol = 'BODY.PEEK[]' if self.service_config['server'] == 'imap.mail.me.com' else protocol
            _, msg_data = self.connection.fetch(message_id, f'({fetch_protocol})')
            self.fetch_count += 1
            time.sleep(self.fetch_delay)
            return True, msg_data[0]
        except Exception as e:
            print(f"Error fetching email {message_id}: {str(e)}")
            return False, None

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_emails_batch(self, message_ids: List[bytes]) -> List[tuple]:
        results = []
        total_batches = (len(message_ids) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(message_ids), self.batch_size):
            batch = message_ids[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            if self.fetch_count >= self.max_fetches_per_session:
                print(f"Warning: Reached max fetches per session ({self.max_fetches_per_session})")
                break
            
            try:
                id_range = b','.join(batch)
                print(f"Fetching batch {batch_num}/{total_batches} ({len(batch)} emails)...")
                _, msg_data = self.connection.fetch(id_range, '(BODY.PEEK[])')
                
                for item in msg_data:
                    if isinstance(item, tuple) and len(item) >= 2:
                        results.append(item)
                
                self.fetch_count += len(batch)
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Batch fetch error for batch {batch_num}: {e}")
                for msg_id in batch:
                    success, email_data = self.fetch_email(msg_id)
                    if success and email_data:
                        results.append(email_data)
        
        return results

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_email_headers(self, message_id: bytes) -> Tuple[bool, Optional[dict]]:
        try:
            if self.fetch_count >= self.max_fetches_per_session:
                print(f"Warning: Reached max fetches per session ({self.max_fetches_per_session})")
                return False, None
            
            _, msg_data = self.connection.fetch(message_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
            self.fetch_count += 1
            time.sleep(self.fetch_delay / 2)
            
            if msg_data and msg_data[0]:
                header_data = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                if isinstance(header_data, bytes):
                    header_text = header_data.decode('utf-8', errors='ignore')
                    headers = {}
                    for line in header_text.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            headers[key.strip().lower()] = value.strip()
                    return True, headers
            
            return False, None
        except Exception as e:
            print(f"Error fetching email headers {message_id}: {str(e)}")
            return False, None

    def get_fetch_stats(self) -> dict:
        return {
            'fetch_count': self.fetch_count,
            'max_fetches': self.max_fetches_per_session,
            'remaining': self.max_fetches_per_session - self.fetch_count
        }

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