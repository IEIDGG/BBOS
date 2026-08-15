import imaplib
import ssl
import re
import socket
import time
import json
import sys
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Set
from functools import wraps
from order_extraction.config.settings import EMAIL_SERVERS

logger = logging.getLogger(__name__)

SOCKET_TIMEOUT = 120
RECONNECT_ATTEMPTS = 3
RECONNECT_BASE_DELAY = 2

CONNECTION_ERROR_MARKERS = (
    'socket error',
    'eof occurred',
    'connection reset',
    'connection closed',
    'connection aborted',
    'broken pipe',
    'not connected',
    'timed out',
    'timeout',
    'bad file descriptor',
    'server not connected',
    'terminating connection',
)


def is_connection_error(error: BaseException) -> bool:
    if isinstance(error, (imaplib.IMAP4.abort, ssl.SSLError, socket.error, OSError)):
        return True
    message = str(error).lower()
    return any(marker in message for marker in CONNECTION_ERROR_MARKERS)


def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(
                            "%s failed after %s attempts: %s",
                            func.__name__, max_retries, e,
                        )
                        raise
                    if is_connection_error(e):
                        logger.warning(
                            "%s lost the IMAP connection (%s); reconnecting",
                            func.__name__, e,
                        )
                        if not self.reconnect(f"{func.__name__}: {e}"):
                            raise
                        continue
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Retry %s/%s for %s after %ss due to: %s",
                        attempt + 1, max_retries, func.__name__, delay, e,
                    )
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
        
        cache_dir = Path('cache')
        cache_dir.mkdir(exist_ok=True)
        self.processed_uids_file = cache_dir / f'processed_uids_{email.replace("@", "_").replace(".", "_")}.json'
        self.processed_uids: Set[str] = self._load_processed_uids()
        
        self.is_proton = service_type == 'proton' or self.service_config['server'] in ['127.0.0.1', 'localhost', 'host.docker.internal']
        if self.is_proton:
            self.fetch_delay = 0.01
            self.batch_delay = 0.05
            self.batch_size = 200
            self.max_fetches_per_session = 5000
            print(f"⚡ ProtonMail Bridge detected ({self.service_config['server']}): Using optimized settings (200 batch, 0.01s delay)")
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
        print(f"\n🔄 Session limit reached ({self.max_fetches_per_session} fetches). Refreshing connection...")
        logger.info(
            "Session fetch limit reached (%s); refreshing IMAP connection",
            self.max_fetches_per_session,
        )
        self.save_progress()

        old_count = self.fetch_count
        if not self.reconnect('session fetch limit reached'):
            return False

        self.fetch_count = 0
        print(f"✓ Session refreshed. Reset fetch count from {old_count} to 0")
        return True

    def _close_quietly(self) -> None:
        if not self.connection:
            return
        try:
            self.connection.logout()
        except Exception as e:
            logger.debug("Ignoring error while closing IMAP connection: %s", e)
        finally:
            self.connection = None

    def _select_folder(self, folder: str) -> bool:
        if not folder or not self.connection:
            return False

        if ' ' in folder or '/' in folder:
            folder_variants = [f'"{folder}"', folder]
        else:
            folder_variants = [folder]

        for folder_variant in folder_variants:
            try:
                status, _ = self.connection.select(folder_variant)
                if status == 'OK':
                    self.current_folder = folder
                    return True
            except Exception as e:
                logger.debug("Select failed for %s: %s", folder_variant, e)
        return False

    def reconnect(self, reason: str = '') -> bool:
        logger.warning("Reconnecting to %s (%s)", self.service_config['server'], reason or 'no reason given')
        saved_folder = self.current_folder
        self._close_quietly()

        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            try:
                time.sleep(RECONNECT_BASE_DELAY * attempt)
                self.connect()
                if saved_folder and not self._select_folder(saved_folder):
                    raise imaplib.IMAP4.error(f"Could not re-select folder '{saved_folder}'")
                logger.info(
                    "Reconnected to %s on attempt %s (folder=%s)",
                    self.service_config['server'], attempt, saved_folder or 'none',
                )
                print(f"✓ Reconnected to {self.service_config['server']}")
                return True
            except Exception as e:
                logger.error(
                    "Reconnect attempt %s/%s failed: %s",
                    attempt, RECONNECT_ATTEMPTS, e,
                )
                self._close_quietly()

        print(f"✗ Could not reconnect to {self.service_config['server']}")
        return False

    def ensure_connection(self) -> bool:
        if not self.connection:
            return self.reconnect('no active connection')

        try:
            status, _ = self.connection.noop()
            if status == 'OK':
                return True
            logger.warning("NOOP returned %s; reconnecting", status)
        except Exception as e:
            logger.warning("NOOP failed (%s); reconnecting", e)

        return self.reconnect('failed health check')

    def connect(self) -> None:
        try:
            if self.service_config['use_ssl']:
                context = ssl.create_default_context()
                self.connection = imaplib.IMAP4_SSL(
                    self.service_config['server'],
                    self.service_config['port'],
                    ssl_context=context,
                    timeout=SOCKET_TIMEOUT
                )
            elif self.service_config['server'] == '127.0.0.1':
                self.connection = imaplib.IMAP4(
                    self.service_config['server'],
                    self.service_config['port'],
                    timeout=SOCKET_TIMEOUT
                )
            else:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.connection = imaplib.IMAP4(
                    self.service_config['server'],
                    self.service_config['port'],
                    timeout=SOCKET_TIMEOUT
                )
                self.connection.starttls(ssl_context=context)

            self.connection.login(self.email, self.password)
            logger.info(
                "Connected to %s as %s",
                self.service_config['server'], self.email,
            )
            print(f"Successfully connected to {self.service_config['server']}")
        except Exception as e:
            logger.error("Error connecting to %s: %s", self.service_config['server'], e)
            print(f"Error connecting to email server: {str(e)}")
            self.connection = None
            raise

    def _format_date_for_imap(self, date_str: str) -> str:
        if not date_str:
            return ""

        try:
            clean_date = date_str.replace('after:', '').strip()
            try:
                date_obj = datetime.strptime(clean_date, '%Y/%m/%d')
            except ValueError:
                date_obj = datetime.strptime(clean_date, '%Y-%m-%d')
            
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
            subjects = re.findall(r'"([^"]+)"', criteria_parts['subject'])
            if subjects:
                expr = f'SUBJECT "{subjects[0]}"'
                for subject in subjects[1:]:
                    expr = f'OR ({expr}) (SUBJECT "{subject}")'
                formatted_parts.append(f'({expr})' if len(subjects) > 1 else expr)

        return ' '.join(formatted_parts)

    def _encode_q_subject(self, text: str) -> str:
        bytes_data = text.encode('utf-8')
        encoded_parts = []
        for b in bytes_data:
            if 33 <= b <= 126 and b != 61:
                encoded_parts.append(chr(b))
            elif b == 32:
                encoded_parts.append('_')
            else:
                encoded_parts.append(f'={b:02X}')
        return "".join(encoded_parts)

    def _ascii_subject(self, text: str) -> str:
        ascii_only = text.encode('ascii', 'ignore').decode('ascii')
        return re.sub(r'\s+', ' ', ascii_only).strip()

    def _subject_search_variants(self, subject: str) -> List[str]:
        variants = []
        seen = set()

        def _add(value: str):
            cleaned = (value or '').strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                variants.append(cleaned)

        original = (subject or '').strip()
        ascii_subject = self._ascii_subject(original)

        if self.is_proton and any(ord(c) > 127 for c in original):
            _add(original)

        _add(ascii_subject)

        if ascii_subject and ' ' in ascii_subject:
            _add(ascii_subject.replace(' ', '_'))

        if original and any(ord(c) > 127 for c in original):
            _add(self._encode_q_subject(original))

        logger.debug(
            "Subject search variants for %r -> %s",
            original[:80],
            variants,
        )
        return variants

    def _expand_subject_criteria(self, search_criteria: dict) -> dict:
        new_criteria = search_criteria.copy()
        subject_criteria = new_criteria.get('subject')
        if not subject_criteria:
            return new_criteria

        raw_subjects = re.findall(r'"([^"]+)"', subject_criteria)
        if not raw_subjects:
            return new_criteria

        expanded = []
        seen = set()
        for subject in raw_subjects:
            for variant in self._subject_search_variants(subject):
                if variant not in seen:
                    seen.add(variant)
                    expanded.append(variant)

        if not expanded:
            return new_criteria

        if len(expanded) == 1:
            new_criteria['subject'] = f'SUBJECT "{expanded[0]}"'
        else:
            parts = ' '.join(f'(SUBJECT "{subject}")' for subject in expanded)
            new_criteria['subject'] = f'(OR {parts})'

        logger.info(
            "Expanded %s subject criteria into %s variant(s)",
            'Proton' if self.is_proton else 'IMAP',
            len(expanded),
        )
        return new_criteria

    def _to_ascii_criteria(self, formatted_criteria: str) -> str:
        ascii_only = formatted_criteria.encode('ascii', 'ignore').decode('ascii')

        def _trim_quoted(match):
            inner = re.sub(r'\s+', ' ', match.group(1)).strip()
            return f'"{inner}"'

        ascii_only = re.sub(r'"([^"]*)"', _trim_quoted, ascii_only)
        ascii_only = re.sub(r'\s+', ' ', ascii_only).strip()
        return ascii_only

    def _run_search(self, formatted_criteria: str, use_uid: bool):
        if not formatted_criteria.strip():
            logger.warning("Empty search criteria; defaulting to ALL")
            formatted_criteria = 'ALL'

        def _search(criteria: str, charset: Optional[str]):
            try:
                return _send_search(criteria, charset)
            except Exception as e:
                if not is_connection_error(e):
                    raise
                logger.warning("SEARCH lost the connection (%s); reconnecting", e)
                if not self.reconnect(f"search: {e}"):
                    raise
                return _send_search(criteria, charset)

        def _send_search(criteria: str, charset: Optional[str]):
            criteria_bytes = criteria.encode('ascii' if charset is None else 'utf-8')
            if use_uid:
                if charset is None:
                    typ, data = self.connection.uid('search', criteria_bytes)
                else:
                    typ, data = self.connection.uid('search', 'CHARSET', charset, criteria_bytes)
            else:
                typ, data = self.connection.search(charset, criteria_bytes)
            if typ != 'OK':
                raise imaplib.IMAP4.error(f"SEARCH returned {typ}: {data}")
            return data

        if formatted_criteria.isascii():
            return _search(formatted_criteria, None)

        try:
            return _search(formatted_criteria, 'UTF-8')
        except imaplib.IMAP4.error as e:
            ascii_criteria = self._to_ascii_criteria(formatted_criteria) or 'ALL'
            logger.warning(
                "UTF-8 search failed (%s); retrying with ASCII criteria: %s",
                e, ascii_criteria,
            )
            return _search(ascii_criteria, None)

    def search_emails(self, folder: str, search_criteria: dict, use_uid_filter: bool = True) -> Tuple[bool, list]:
        spinner = None
        try:
            if not self._select_folder(folder):
                logger.warning("Could not select folder '%s'; reconnecting", folder)
                self.current_folder = folder
                if not self.reconnect(f"select folder '{folder}'"):
                    raise Exception(f"Could not select folder '{folder}' after reconnect")
            
            search_criteria = self._expand_subject_criteria(search_criteria)

            formatted_criteria = self._format_search_criteria(search_criteria)
            if not self.is_proton and not formatted_criteria.isascii():
                ascii_fallback = self._to_ascii_criteria(formatted_criteria)
                logger.warning(
                    "Non-ASCII IMAP criteria for non-Proton account; using ASCII fallback: %s",
                    ascii_fallback,
                )
                formatted_criteria = ascii_fallback
            print(f"Using IMAP search criteria: {formatted_criteria}")
            logger.info("IMAP search criteria: %s", formatted_criteria)
            
            spinner = ProgressSpinner(f"Searching folder '{folder}'")
            spinner.start()
            
            try:
                if use_uid_filter:
                    uid_data = self._run_search(formatted_criteria, use_uid=True)
                    
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
                    message_numbers = self._run_search(formatted_criteria, use_uid=False)

                    spinner.stop()
                    
                    if message_numbers[0]:
                        return True, message_numbers[0].split()
                    return True, []

            except imaplib.IMAP4.error as e:
                if spinner: spinner.stop()
                logger.error("IMAP search failed in folder '%s': %s", folder, e)
                print(f"⚠ Search failed: {e}")
                return False, []

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
            
            id_range = b','.join(batch)
            print(f"Fetching batch {batch_num}/{total_batches} ({len(batch)} emails)...")

            try:
                msg_data = self._fetch_range(id_range, use_uid)
            except Exception as e:
                if is_connection_error(e):
                    logger.warning(
                        "Batch %s/%s lost the connection (%s); reconnecting",
                        batch_num, total_batches, e,
                    )
                    if not self.reconnect(f"batch fetch {batch_num}: {e}"):
                        logger.error(
                            "Reconnect failed; stopping batch fetch at batch %s/%s",
                            batch_num, total_batches,
                        )
                        break
                    try:
                        msg_data = self._fetch_range(id_range, use_uid)
                    except Exception as retry_error:
                        logger.error(
                            "Batch %s/%s failed after reconnect: %s",
                            batch_num, total_batches, retry_error,
                        )
                        results.extend(self._fetch_individually(batch, use_uid))
                        continue
                else:
                    error_str = str(e).lower()
                    if 'no such message' in error_str or 'invalid message' in error_str:
                        print(f"Some messages in batch {batch_num} no longer exist, fetching individually...")
                    else:
                        logger.warning("Batch fetch error for batch %s: %s", batch_num, e)
                        print(f"Batch fetch error for batch {batch_num}: {e}")
                    results.extend(self._fetch_individually(batch, use_uid))
                    continue

            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    results.append(item)

            self.fetch_count += len(batch)
            time.sleep(self.batch_delay)

        return results

    def _fetch_range(self, id_range: bytes, use_uid: bool):
        if use_uid:
            _, msg_data = self.connection.uid('fetch', id_range, '(BODY.PEEK[])')
        else:
            _, msg_data = self.connection.fetch(id_range, '(BODY.PEEK[])')
        return msg_data or []

    def _fetch_individually(self, batch: List[bytes], use_uid: bool) -> List[tuple]:
        results = []
        for msg_id in batch:
            try:
                success, email_data = self.fetch_email(msg_id, use_uid=use_uid)
            except Exception as e:
                logger.error("Skipping message %s after fetch failure: %s", msg_id, e)
                if not self.connection:
                    logger.error("Connection is down; aborting individual fetches")
                    break
                continue
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
            if is_connection_error(e):
                raise
            logger.error("Error fetching email headers %s: %s", message_id, e)
            print(f"Error fetching email headers {message_id}: {str(e)}")
            return False, None
    
    def fetch_headers_batch(self, message_ids: List[bytes], use_uid: bool = True) -> List[Tuple[bytes, dict]]:
        results = []
        for msg_id in message_ids:
            try:
                success, headers = self.fetch_email_headers(msg_id, use_uid=use_uid)
            except Exception as e:
                logger.error("Header fetch failed for %s: %s", msg_id, e)
                if not self.connection:
                    logger.error("Connection is down; aborting header fetches")
                    break
                continue
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
                    except Exception:
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
                    except socket.timeout:
                        continue
                    except Exception as e:
                        logger.warning("IDLE read failed: %s", e)
                        if is_connection_error(e):
                            self.reconnect(f"idle: {e}")
                            return None
                        continue
                
                self.connection.send(b'DONE\r\n')
                self.connection.readline()
                return False
            except Exception as e:
                logger.warning("IDLE failed on folder '%s': %s", folder, e)
                try:
                    self.connection.send(b'DONE\r\n')
                    self.connection.readline()
                except Exception:
                    pass
                if is_connection_error(e):
                    self.reconnect(f"idle: {e}")
                return None
            finally:
                try:
                    if self.connection:
                        self.connection.socket().settimeout(SOCKET_TIMEOUT)
                except Exception as e:
                    logger.debug("Could not restore socket timeout: %s", e)
        except Exception as e:
            logger.warning("idle_wait error on folder '%s': %s", folder, e)
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
