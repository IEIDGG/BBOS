import imaplib
import ssl
import re
import time
import json
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Set
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


class ProgressSpinner:
    def __init__(self, message="Processing"):
        self.message = message
        self.spinning = False
        self.thread = None
        self.start_time = None
        self.spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        
    def _spin(self):
        idx = 0
        while self.spinning:
            elapsed = time.time() - self.start_time
            sys.stdout.write(f'\r{self.spinner_chars[idx]} {self.message} ({elapsed:.1f}s)')
            sys.stdout.flush()
            idx = (idx + 1) % len(self.spinner_chars)
            time.sleep(0.1)
    
    def start(self):
        self.spinning = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
    
    def stop(self):
        self.spinning = False
        if self.thread:
            self.thread.join(timeout=0.5)
        elapsed = time.time() - self.start_time if self.start_time else 0
        sys.stdout.write(f'\r✓ {self.message} completed in {elapsed:.1f}s\n')
        sys.stdout.flush()


class EmailConnector:
    def __init__(self, email: str, password: str, service_type: str):
        self.email = email
        self.password = password
        self.service_config = EMAIL_SERVERS.get(service_type, EMAIL_SERVERS['gmail'])
        self.connection: Optional[imaplib.IMAP4] = None
        self.fetch_count = 0
        self.current_folder: Optional[str] = None
        
        self.processed_uids_file = Path(f'.processed_uids_{email.replace("@", "_").replace(".", "_")}.json')
        self.processed_uids: Set[str] = self._load_processed_uids()
        
        if self.service_config['server'] == '127.0.0.1':
            self.fetch_delay = 0.01
            self.batch_delay = 0.05
            self.batch_size = 200
            self.max_fetches_per_session = 5000
            print("⚡ ProtonMail Bridge detected: Using optimized settings (200 batch, 0.01s delay)")
        else:
            self.fetch_delay = 0.1
            self.batch_delay = 0.5
            self.batch_size = 50
            self.max_fetches_per_session = 1000

    def _load_processed_uids(self) -> Set[str]:
        if self.processed_uids_file.exists():
            try:
                with open(self.processed_uids_file, 'r') as f:
                    data = json.load(f)
                    print(f"📋 Loaded {len(data)} processed email UIDs from cache")
                    return set(data)
            except Exception as e:
                print(f"Warning: Could not load processed UIDs: {e}")
        return set()
    
    def _save_processed_uids(self) -> None:
        try:
            with open(self.processed_uids_file, 'w') as f:
                json.dump(list(self.processed_uids), f)
        except Exception as e:
            print(f"Warning: Could not save processed UIDs: {e}")
    
    def mark_uid_processed(self, uid: bytes) -> None:
        uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
        self.processed_uids.add(uid_str)
    
    def save_progress(self) -> None:
        self._save_processed_uids()
        print(f"💾 Saved {len(self.processed_uids)} processed UIDs to cache")

    def _refresh_session(self) -> bool:
        try:
            print(f"\n🔄 Session limit reached ({self.max_fetches_per_session} fetches). Refreshing connection...")
            self.save_progress()
            
            saved_folder = self.current_folder
            
            if self.connection:
                try:
                    self.connection.logout()
                except Exception:
                    pass
                finally:
                    self.connection = None
            
            time.sleep(1)
            
            self.connect()
            old_count = self.fetch_count
            self.fetch_count = 0
            
            if saved_folder:
                try:
                    folder_variants = []
                    if ' ' in saved_folder or '/' in saved_folder:
                        folder_variants = [f'"{saved_folder}"', saved_folder]
                    else:
                        folder_variants = [saved_folder]
                    
                    for folder_variant in folder_variants:
                        try:
                            status, _ = self.connection.select(folder_variant)
                            if status == 'OK':
                                print(f"✓ Session refreshed. Reset fetch count from {old_count} to 0. Re-selected folder: {saved_folder}")
                                return True
                        except Exception:
                            continue
                    print(f"⚠ Session refreshed but could not re-select folder: {saved_folder}")
                except Exception as e:
                    print(f"⚠ Session refreshed but error re-selecting folder: {str(e)}")
            else:
                print(f"✓ Session refreshed. Reset fetch count from {old_count} to 0")
            
            return True
        except Exception as e:
            print(f"✗ Error refreshing session: {str(e)}")
            return False

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

    def search_emails(self, folder: str, search_criteria: dict, use_uid_filter: bool = True) -> Tuple[bool, list]:
        spinner = None
        try:
            folder_variants = []
            if ' ' in folder or '/' in folder:
                folder_variants = [f'"{folder}"', folder]
            else:
                folder_variants = [folder]
            
            selected = False
            for folder_variant in folder_variants:
                try:
                    status, response = self.connection.select(folder_variant)
                    if status == 'OK':
                        selected = True
                        self.current_folder = folder
                        break
                except Exception:
                    continue
            
            if not selected:
                raise Exception(f"Could not select folder '{folder}' (tried: {', '.join(folder_variants)})")
            
            formatted_criteria = self._format_search_criteria(search_criteria)
            print(f"Using IMAP search criteria: {formatted_criteria}")
            
            spinner = ProgressSpinner(f"Searching folder '{folder}'")
            spinner.start()
            
            if use_uid_filter:
                try:
                    criteria_bytes = formatted_criteria.encode('utf-8')
                    _, uid_data = self.connection.uid('search', 'CHARSET', 'UTF-8', criteria_bytes)
                except imaplib.IMAP4.error as e:
                    print(f"⚠ UTF-8 search failed, retrying with ASCII: {e}")
                    _, uid_data = self.connection.uid('search', None, formatted_criteria)
                
                spinner.stop()
                
                if uid_data[0]:
                    all_uids = uid_data[0].split()
                    
                    if len(all_uids) > 100:
                        print(f"🔄 Filtering {len(all_uids)} emails against processed cache...")
                        filter_start = time.time()
                        new_uids = []
                        for i, uid in enumerate(all_uids):
                            if uid.decode() not in self.processed_uids:
                                new_uids.append(uid)
                            if i % 500 == 0 and i > 0:
                                sys.stdout.write(f'\r  Filtered {i}/{len(all_uids)} emails...')
                                sys.stdout.flush()
                        filter_time = time.time() - filter_start
                        sys.stdout.write(f'\r✓ Filtered {len(all_uids)} emails in {filter_time:.1f}s\n')
                        sys.stdout.flush()
                    else:
                        new_uids = [uid for uid in all_uids if uid.decode() not in self.processed_uids]
                    
                    print(f"📊 Found {len(all_uids)} total emails, {len(new_uids)} new (skipping {len(all_uids) - len(new_uids)} already processed)")
                    return True, new_uids
                
                return True, []
            else:
                try:
                    criteria_bytes = formatted_criteria.encode('utf-8')
                    _, message_numbers = self.connection.search('UTF-8', criteria_bytes)
                except imaplib.IMAP4.error as e:
                    print(f"⚠ UTF-8 search failed, retrying with ASCII: {e}")
                    _, message_numbers = self.connection.search(None, formatted_criteria)

                spinner.stop()
                
                if message_numbers[0]:
                    return True, message_numbers[0].split()
                return True, []
        except Exception as e:
            try:
                if spinner:
                    spinner.stop()
            except:
                pass
            print(f"Error searching emails in {folder}: {str(e)}")
            return False, []

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_email(self, message_id: bytes, protocol: str = 'BODY.PEEK[]', use_uid: bool = True) -> Tuple[bool, Optional[tuple]]:
        try:
            if self.fetch_count >= self.max_fetches_per_session:
                if not self._refresh_session():
                    return False, None
            
            fetch_protocol = 'BODY.PEEK[]' if self.service_config['server'] == 'imap.mail.me.com' else protocol
            
            if use_uid:
                _, msg_data = self.connection.uid('fetch', message_id, f'({fetch_protocol})')
            else:
                _, msg_data = self.connection.fetch(message_id, f'({fetch_protocol})')
            
            if not msg_data or not msg_data[0]:
                return False, None
            
            self.fetch_count += 1
            time.sleep(self.fetch_delay)
            return True, msg_data[0]
        except imaplib.IMAP4.error as e:
            error_str = str(e).lower()
            if 'no such message' in error_str or 'invalid message' in error_str:
                return False, None
            raise
        except Exception as e:
            error_str = str(e).lower()
            if 'no such message' in error_str or 'invalid message' in error_str:
                return False, None
            print(f"Error fetching email {message_id}: {str(e)}")
            raise

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_emails_batch(self, message_ids: List[bytes], use_uid: bool = True) -> List[tuple]:
        results = []
        total_batches = (len(message_ids) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(message_ids), self.batch_size):
            batch = message_ids[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            if self.fetch_count >= self.max_fetches_per_session:
                if not self._refresh_session():
                    break
            
            try:
                id_range = b','.join(batch)
                print(f"Fetching batch {batch_num}/{total_batches} ({len(batch)} emails)...")
                
                if use_uid:
                    _, msg_data = self.connection.uid('fetch', id_range, '(BODY.PEEK[])')
                else:
                    _, msg_data = self.connection.fetch(id_range, '(BODY.PEEK[])')
                
                for item in msg_data:
                    if isinstance(item, tuple) and len(item) >= 2:
                        results.append(item)
                
                self.fetch_count += len(batch)
                time.sleep(self.batch_delay)
                
            except imaplib.IMAP4.error as e:
                error_str = str(e).lower()
                if 'no such message' in error_str or 'invalid message' in error_str:
                    print(f"Some messages in batch {batch_num} no longer exist, fetching individually...")
                    for msg_id in batch:
                        success, email_data = self.fetch_email(msg_id, use_uid=use_uid)
                        if success and email_data:
                            results.append(email_data)
                else:
                    print(f"Batch fetch error for batch {batch_num}: {e}")
                    for msg_id in batch:
                        success, email_data = self.fetch_email(msg_id, use_uid=use_uid)
                        if success and email_data:
                            results.append(email_data)
            except Exception as e:
                error_str = str(e).lower()
                if 'no such message' in error_str or 'invalid message' in error_str:
                    print(f"Some messages in batch {batch_num} no longer exist, fetching individually...")
                    for msg_id in batch:
                        success, email_data = self.fetch_email(msg_id, use_uid=use_uid)
                        if success and email_data:
                            results.append(email_data)
                else:
                    print(f"Batch fetch error for batch {batch_num}: {e}")
                    for msg_id in batch:
                        success, email_data = self.fetch_email(msg_id, use_uid=use_uid)
                        if success and email_data:
                            results.append(email_data)
        
        return results

    @retry_with_backoff(max_retries=3, base_delay=1)
    def fetch_email_headers(self, message_id: bytes, use_uid: bool = True) -> Tuple[bool, Optional[dict]]:
        try:
            if self.fetch_count >= self.max_fetches_per_session:
                if not self._refresh_session():
                    return False, None
            
            if use_uid:
                _, msg_data = self.connection.uid('fetch', message_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
            else:
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
    
    def fetch_headers_batch(self, message_ids: List[bytes], use_uid: bool = True) -> List[Tuple[bytes, dict]]:
        results = []
        for msg_id in message_ids:
            success, headers = self.fetch_email_headers(msg_id, use_uid=use_uid)
            if success and headers:
                results.append((msg_id, headers))
        return results
    
    def filter_by_subject_keywords(self, message_ids: List[bytes], keywords: List[str], use_uid: bool = True) -> List[bytes]:
        print(f"🔍 Pre-filtering {len(message_ids)} emails by subject keywords...")
        headers_data = self.fetch_headers_batch(message_ids, use_uid=use_uid)
        
        filtered = []
        for msg_id, headers in headers_data:
            subject = headers.get('subject', '').lower()
            if any(keyword.lower() in subject for keyword in keywords):
                filtered.append(msg_id)
        
        print(f"✓ Filtered to {len(filtered)}/{len(message_ids)} relevant emails")
        return filtered

    def idle_wait(self, folder: str, timeout: int = 30) -> Optional[bool]:
        try:
            if not self.connection:
                return None
            
            quoted_folder = f'"{folder}"' if ' ' in folder or '/' in folder else folder
            
            try:
                typ, data = self.connection.select(quoted_folder)
                if typ != 'OK':
                    return None
                self.current_folder = folder
            except Exception as e:
                return None
            
            try:
                tag = self.connection._new_tag()
                self.connection.send(f'{tag.decode()} IDLE\r\n'.encode())
                
                response = self.connection.readline()
                if b'+ idling' not in response.lower() and b'+ waiting' not in response.lower():
                    try:
                        self.connection.readline()
                    except:
                        pass
                    return None
                
                start_time = time.time()
                while time.time() - start_time < timeout:
                    try:
                        self.connection.socket().settimeout(1)
                        data = self.connection.readline()
                        if data and (b'EXISTS' in data or b'RECENT' in data):
                            self.connection.send(b'DONE\r\n')
                            self.connection.readline()
                            return True
                    except Exception:
                        continue
                
                self.connection.send(b'DONE\r\n')
                self.connection.readline()
                return False
            except Exception:
                try:
                    self.connection.send(b'DONE\r\n')
                    self.connection.readline()
                except:
                    pass
                return None
        except Exception as e:
            return None

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
                self.save_progress()
                self.connection.logout()
                print("Email connection closed successfully")
            except Exception as e:
                print(f"Error disconnecting: {str(e)}")
            finally:
                self.connection = None