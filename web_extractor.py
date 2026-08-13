import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
import copy

from email_processing.connector import EmailConnector
from email_processing.handlers import OrderEmailHandler, AmazonEmailHandler, CostcoEmailHandler, WalmartEmailHandler
from order_extraction.config.settings import SEARCH_CRITERIA, AMAZON_SEARCH_CRITERIA, COSTCO_SEARCH_CRITERIA, WALMART_SEARCH_CRITERIA
from config.supabase import is_supabase_initialized, get_service_client
from services.supabase_service import insert_order_safely, build_order_fulfillment_updates

logger = logging.getLogger(__name__)


class WebOrderExtractor:
    def __init__(
        self,
        email: str,
        password: str,
        service_type: str,
        user_uid: str,
        progress_callback: Optional[Callable[[int, str, Dict], None]] = None,
        mark_payment_declined_as_cancelled: bool = True
    ):
        self.email = email
        self.password = password
        self.service_type = service_type
        self.user_uid = user_uid
        self.progress_callback = progress_callback
        self.mark_payment_declined_as_cancelled = mark_payment_declined_as_cancelled
        self.connector = None
        self.processed_uids = set()
        self.stats = {
            'processed': 0,
            'orders_found': 0,
            'new_orders': 0,
            'updated_orders': 0,
            'found': 0,
            'added_details': [],
            'updated_details': [],
            'cancelled_details': [],
            'payment_declined_details': []
        }
    
    def _update_progress(self, progress: int, message: str):
        if self.progress_callback:
            self.progress_callback(progress, message, self.stats)
    
    def _load_processed_uids(self):
        try:
            if not is_supabase_initialized():
                self.processed_uids = set()
                return
                
            client = get_service_client()
            result = client.table('user_cache').select('processed_uids').eq('user_id', self.user_uid).limit(1).execute()
            
            if result.data and result.data[0].get('processed_uids'):
                data = result.data[0]['processed_uids']
                if isinstance(data, list):
                    self.processed_uids = set(data)
                    logger.info(f"Loaded {len(self.processed_uids)} processed UIDs from database")
                else:
                    self.processed_uids = set()
            else:
                self.processed_uids = set()
        except Exception as e:
            logger.error(f"Error loading processed UIDs: {e}")
            self.processed_uids = set()
    
    def _save_processed_uids(self):
        try:
            if not is_supabase_initialized():
                return

            import json
            client = get_service_client()
            uids_list = list(self.processed_uids)[-5000:]

            client.table('user_cache').upsert({
                'user_id': self.user_uid,
                'processed_uids': json.dumps(uids_list),
                'updated_at': datetime.utcnow().isoformat()
            }, on_conflict='user_id')

            logger.info(f"Saved {len(uids_list)} processed UIDs to database")
        except Exception as e:
            logger.error(f"Error saving processed UIDs: {e}")
    
    def _mark_uid_processed(self, uid):
        uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
        self.processed_uids.add(uid_str)
    
    def _get_existing_orders(self) -> Dict[str, Dict]:
        try:
            if not is_supabase_initialized():
                return {}
                
            client = get_service_client()
            result = client.table('orders').select(
                'id, order_number, order_date, tracking_number, status, state, zip, zip_and_state, '
                'delivered_on_date, estimated_delivery, order_details_link, email_address, '
                'item_title, total_price'
            ).eq('user_id', self.user_uid).execute()
            
            existing = {}
            for order in (result.data or []):
                order_num = order.get('order_number', '')
                if order_num:
                    existing[order_num] = {'key': order.get('id'), 'data': order}
            return existing
        except Exception as e:
            logger.error(f"Error getting existing orders: {e}")
            return {}
    
    def _save_order_to_supabase(self, order: Dict, existing_orders: Dict) -> bool:
        try:
            if not is_supabase_initialized():
                return False

            if (order.get('website') or '').lower() == 'bestbuy':
                from services.bestbuy_email_parser import enrich_bestbuy_order
                enrich_bestbuy_order(order)
                
            order_number = order.get('order_number', order.get('number', ''))
            if not order_number:
                return False
            
            zip_code = order.get('zip', '')
            state = order.get('state', '')
            zip_and_state = order.get('zip_and_state') or ' '.join([part for part in [zip_code, state] if part])
            
            order_data = {
                'user_id': self.user_uid,
                'website': order.get('website', ''),
                'order_number': order_number,
                'order_date': order.get('date', order.get('order_date', '')),
                'total_price': order.get('total_price', ''),
                'status': order.get('status', ''),
                'item_title': order.get('products', [{}])[0].get('title', '') if order.get('products') else '',
                'quantity': str(order.get('products', [{}])[0].get('quantity', '1')) if order.get('products') else '',
                'tracking_number': order.get('tracking', []),
                'state': state,
                'zip': zip_code,
                'email_address': order.get('email_address', ''),
                'item_image': '',
                'delivered_on_date': '',
                'zip_and_state': zip_and_state,
                'estimated_delivery': order.get('estimated_delivery', ''),
                'order_details_link': order.get('order_details_link', '')
            }

            if order_data.get('status') == 'Payment Declined' and order_data.get('tracking_number'):
                order_data['status'] = 'Shipped'
            
            client = get_service_client()
            
            order_id = None
            if order_number in existing_orders:
                existing = existing_orders[order_number]
                existing_data = existing['data']
                order_id = existing['key']
                updates = {}
                existing_tracking = existing_data.get('tracking_number', []) or []
                if isinstance(existing_tracking, str):
                    existing_tracking = [existing_tracking] if existing_tracking else []
                existing_status = existing_data.get('status', '')

                if order_data.get('status') == 'Payment Declined':
                    if existing_tracking or str(existing_status).lower() == 'shipped':
                        order_data['status'] = 'Shipped'
                elif (
                    order_data.get('status') == 'Cancelled'
                    and order.get('status_reason') == 'payment_declined'
                    and str(existing_status).lower() == 'payment declined'
                ):
                    order_data['status'] = 'Payment Declined'

                if order_data.get('tracking_number'):
                    new_tracking = order_data['tracking_number']
                    if isinstance(new_tracking, str):
                        new_tracking = [new_tracking] if new_tracking else []
                    combined = list(set(existing_tracking + new_tracking))
                    if combined != existing_tracking:
                        updates['tracking_number'] = combined

                if order_data.get('status') and order_data['status'] != existing_data.get('status'):
                    updates['status'] = order_data['status']

                updates.update(build_order_fulfillment_updates(existing_data, order_data))
                if order_data.get('item_title') and not existing_data.get('item_title'):
                    updates['item_title'] = order_data['item_title']
                if order_data.get('total_price') and not existing_data.get('total_price'):
                    updates['total_price'] = order_data['total_price']

                if updates:
                    client.table('orders').update(updates).eq('id', existing['key']).execute()
                    existing_data.update(updates)
                    self.stats['updated_orders'] += 1
                    
                    update_record = {
                        'order_number': order_number,
                        'updates': updates,
                        'website': order.get('website', '')
                    }
                    if updates.get('status') == 'Cancelled':
                        self.stats['cancelled_details'].append(update_record)
                    elif updates.get('status') == 'Payment Declined':
                        self.stats.setdefault('payment_declined_details', []).append(update_record)
                        self.stats['updated_details'].append(update_record)
                    else:
                        self.stats['updated_details'].append(update_record)
            else:
                success, new_id, msg = insert_order_safely(self.user_uid, order_data)
                if success:
                    order_id = new_id
                self.stats['new_orders'] += 1
                
                self.stats['added_details'].append({
                    'order_number': order_number,
                    'website': order.get('website', ''),
                    'status': order_data.get('status', ''),
                    'total_price': order_data.get('total_price', '')
                })

            # Save individual items to order_items table
            if order_id and order.get('products'):
                try:
                    client.table('order_items').delete().eq('order_id', order_id).execute()
                    for idx, product in enumerate(order.get('products', [])):
                        client.table('order_items').insert({
                            'order_id': order_id,
                            'user_id': self.user_uid,
                            'item_title': product.get('title', ''),
                            'model_number': product.get('model_number', ''),
                            'quantity': int(product.get('quantity', 1) or 1),
                            'unit_price': product.get('price', ''),
                            'position': idx,
                        }).execute()
                except Exception as e:
                    logger.error(f"Error saving order items: {e}")

            return order_id is not None
                
        except Exception as e:
            logger.error(f"Error saving order to database: {e}")
            return False
    
    def extract_orders(
        self,
        service: str,
        folder: str,
        date_filter: Optional[str] = None,
        ignore_cache: bool = False,
        email_types: Optional[List[str]] = None
    ) -> Dict:
        if email_types is None:
            email_types = ['confirmation', 'cancellation', 'shipped']
        try:
            self._update_progress(5, 'Loading cache...')
            if not ignore_cache:
                self._load_processed_uids()
            
            self._update_progress(10, 'Connecting to email server...')
            self.connector = EmailConnector(self.email, self.password, self.service_type)
            
            if not ignore_cache:
                self.connector.processed_uids = self.processed_uids
            
            self.connector.connect()
            
            self._update_progress(15, 'Connected. Fetching existing orders...')
            existing_orders = self._get_existing_orders()
            
            services_to_process = []
            if service == 'all':
                services_to_process = ['bestbuy', 'amazon', 'costco', 'walmart']
            else:
                services_to_process = [service]
            
            total_services = len(services_to_process)
            progress_per_service = 70 // total_services
            
            for idx, svc in enumerate(services_to_process):
                base_progress = 20 + (idx * progress_per_service)
                self._update_progress(base_progress, f'Processing {svc.title()} orders...')
                
                if svc == 'bestbuy':
                    self._process_bestbuy(folder, date_filter, ignore_cache, existing_orders, base_progress, progress_per_service, email_types)
                elif svc == 'amazon':
                    self._process_amazon(folder, date_filter, ignore_cache, existing_orders, base_progress, progress_per_service, email_types)
                elif svc == 'costco':
                    self._process_costco(folder, date_filter, ignore_cache, existing_orders, base_progress, progress_per_service, email_types)
                elif svc == 'walmart':
                    self._process_walmart(folder, date_filter, ignore_cache, existing_orders, base_progress, progress_per_service, email_types)
            
            self._update_progress(90, 'Saving cache...')
            if not ignore_cache:
                self.processed_uids = self.connector.processed_uids
                self._save_processed_uids()
            
            self._update_progress(95, 'Disconnecting...')
            self.connector.disconnect()
            
            self._update_progress(100, 'Import completed')
            
            return {
                'success': True,
                'stats': self.stats
            }
            
        except Exception as e:
            logger.error(f"Error extracting orders: {e}")
            if self.connector:
                try:
                    self.connector.disconnect()
                except:
                    pass
            return {
                'success': False,
                'error': str(e),
                'stats': self.stats
            }
    
    def _process_bestbuy(self, folder: str, date_filter: Optional[str], ignore_cache: bool, existing_orders: Dict, base_progress: int, progress_range: int, email_types: List[str]):
        try:
            handler = OrderEmailHandler(self.connector)
            orders = []
            
            if 'confirmation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.1), 'Searching Best Buy confirmation emails...')
                
                search_criteria = self._get_search_criteria_with_date(SEARCH_CRITERIA, 'confirmation', date_filter)
                use_uid_filter = not ignore_cache
                success, messages = self.connector.search_emails(folder, search_criteria, use_uid_filter=use_uid_filter)
                
                if success and messages:
                    self.stats['found'] += len(messages)
                    self._update_progress(base_progress + int(progress_range * 0.2), f'Found {len(messages)} Best Buy confirmation emails...')
                    
                    orders = handler.process_confirmation_emails(folder, ignore_cache=ignore_cache, date_filter=date_filter)
            
            if 'cancellation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.4), 'Processing cancellation emails...')
                handler.process_cancellation_emails(
                    folder,
                    orders,
                    ignore_cache=ignore_cache,
                    date_filter=date_filter,
                    mark_payment_declined_as_cancelled=self.mark_payment_declined_as_cancelled
                )
            
            if 'shipped' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.6), 'Processing shipped emails...')
                handler.process_shipped_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)

            if any(email_type in email_types for email_type in ('confirmation', 'cancellation', 'shipped')):
                self._update_progress(base_progress + int(progress_range * 0.7), 'Saving Best Buy orders...')
                for order in orders:
                    order['website'] = 'BestBuy'
                    self._save_order_to_supabase(order, existing_orders)
                    self.stats['orders_found'] += 1
                    self.stats['processed'] += 1

            if 'price_match_credit' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.85), 'Processing price match credit emails...')
                credits = handler.process_price_match_credit_emails(folder, ignore_cache=ignore_cache, date_filter=date_filter)
                if credits:
                    self._apply_price_match_credits(credits)

            self._update_progress(base_progress + progress_range, 'Best Buy processing complete')
            
        except Exception as e:
            logger.error(f"Error processing Best Buy orders: {e}")
    
    def _process_amazon(self, folder: str, date_filter: Optional[str], ignore_cache: bool, existing_orders: Dict, base_progress: int, progress_range: int, email_types: List[str]):
        try:
            handler = AmazonEmailHandler(self.connector)
            orders = []
            
            if 'confirmation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.1), 'Searching Amazon confirmation emails...')
                
                search_criteria = self._get_search_criteria_with_date(AMAZON_SEARCH_CRITERIA, 'confirmation', date_filter)
                use_uid_filter = not ignore_cache
                success, messages = self.connector.search_emails(folder, search_criteria, use_uid_filter=use_uid_filter)
                
                if success and messages:
                    self.stats['found'] += len(messages)
                    self._update_progress(base_progress + int(progress_range * 0.2), f'Found {len(messages)} Amazon confirmation emails...')
                    
                    orders = handler.process_confirmation_emails(folder, ignore_cache=ignore_cache, date_filter=date_filter)
            
            if 'cancellation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.4), 'Processing cancellation emails...')
                handler.process_cancellation_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)
            
            if 'shipped' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.6), 'Processing shipped emails...')
                handler.process_shipped_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)
                
                self._update_progress(base_progress + int(progress_range * 0.8), 'Saving Amazon orders...')
                for order in orders:
                    order['website'] = 'Amazon'
                    self._save_order_to_supabase(order, existing_orders)
                    self.stats['orders_found'] += 1
                    self.stats['processed'] += 1
            
            self._update_progress(base_progress + progress_range, 'Amazon processing complete')
            
        except Exception as e:
            logger.error(f"Error processing Amazon orders: {e}")
    
    def _process_costco(self, folder: str, date_filter: Optional[str], ignore_cache: bool, existing_orders: Dict, base_progress: int, progress_range: int, email_types: List[str]):
        try:
            handler = CostcoEmailHandler(self.connector)
            orders = []
            
            if 'confirmation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.1), 'Searching Costco confirmation emails...')
                
                search_criteria = self._get_search_criteria_with_date(COSTCO_SEARCH_CRITERIA, 'confirmation', date_filter)
                use_uid_filter = not ignore_cache
                success, messages = self.connector.search_emails(folder, search_criteria, use_uid_filter=use_uid_filter)
                
                if success and messages:
                    self.stats['found'] += len(messages)
                    self._update_progress(base_progress + int(progress_range * 0.2), f'Found {len(messages)} Costco confirmation emails...')
                    
                    orders = handler.process_confirmation_emails(folder, ignore_cache=ignore_cache, date_filter=date_filter)
            
            if 'cancellation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.4), 'Processing cancellation emails...')
                handler.process_cancellation_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)
            
            if 'shipped' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.6), 'Processing shipped emails...')
                handler.process_shipped_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)
                
                self._update_progress(base_progress + int(progress_range * 0.8), 'Saving Costco orders...')
                for order in orders:
                    order['website'] = 'Costco'
                    self._save_order_to_supabase(order, existing_orders)
                    self.stats['orders_found'] += 1
                    self.stats['processed'] += 1
            
            self._update_progress(base_progress + progress_range, 'Costco processing complete')
            
        except Exception as e:
            logger.error(f"Error processing Costco orders: {e}")

    def _process_walmart(self, folder: str, date_filter: Optional[str], ignore_cache: bool, existing_orders: Dict, base_progress: int, progress_range: int, email_types: List[str]):
        try:
            handler = WalmartEmailHandler(self.connector)
            orders = []

            if 'confirmation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.1), 'Searching Walmart confirmation emails...')

                search_criteria = self._get_search_criteria_with_date(WALMART_SEARCH_CRITERIA, 'confirmation', date_filter)
                use_uid_filter = not ignore_cache
                success, messages = self.connector.search_emails(folder, search_criteria, use_uid_filter=use_uid_filter)

                if success and messages:
                    self.stats['found'] += len(messages)
                    self._update_progress(base_progress + int(progress_range * 0.2), f'Found {len(messages)} Walmart confirmation emails...')

                    orders = handler.process_confirmation_emails(folder, ignore_cache=ignore_cache, date_filter=date_filter)

            if 'cancellation' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.4), 'Processing cancellation emails...')
                handler.process_cancellation_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)

            if 'shipped' in email_types:
                self._update_progress(base_progress + int(progress_range * 0.6), 'Processing shipped emails...')
                handler.process_shipped_emails(folder, orders, ignore_cache=ignore_cache, date_filter=date_filter)

                self._update_progress(base_progress + int(progress_range * 0.8), 'Saving Walmart orders...')
                for order in orders:
                    order['website'] = 'Walmart'
                    self._save_order_to_supabase(order, existing_orders)
                    self.stats['orders_found'] += 1
                    self.stats['processed'] += 1

            self._update_progress(base_progress + progress_range, 'Walmart processing complete')

        except Exception as e:
            logger.error(f"Error processing Walmart orders: {e}")

    def _apply_price_match_credits(self, credits: list):
        """Apply price match credits from Best Buy emails to orders in the database.
        Inserts per-product rows into order_price_match_credits (deduped),
        then aggregates totals back to orders.pm_amount_saved.
        Does NOT overwrite pm_status for queued/in_progress/completed orders."""
        try:
            if not is_supabase_initialized():
                return

            import hashlib
            from datetime import datetime, timezone

            client = get_service_client()
            affected_orders = {}  # order_number -> order dict

            for credit in credits:
                order_number = credit['order_number']
                amount_saved = credit['amount_saved']
                product_name = credit.get('product_name', '')
                quantity = credit.get('quantity', 1)
                email_date = credit.get('date', '')
                email_address = credit.get('email_address', '')

                # Find the order in the database
                if order_number not in affected_orders:
                    result = (client.table('orders')
                              .select('id, pm_status, pm_amount_saved')
                              .eq('user_id', self.user_uid)
                              .eq('order_number', order_number)
                              .limit(1)
                              .execute())

                    if not result.data:
                        logger.info(f"Price match credit: Order {order_number} not found in database, skipping")
                        continue
                    affected_orders[order_number] = result.data[0]

                order = affected_orders[order_number]

                # Build dedup key
                name_hash = hashlib.md5(product_name.encode()).hexdigest()[:8] if product_name else ''
                dedup_key = f"{order_number}|{amount_saved}|{email_date}|{name_hash}"

                # Upsert into order_price_match_credits
                try:
                    res = client.table('order_price_match_credits').upsert({
                        'user_id': self.user_uid,
                        'order_id': order['id'],
                        'order_number': order_number,
                        'product_name': product_name,
                        'quantity': quantity,
                        'amount_saved': float(amount_saved),
                        'email_date': email_date,
                        'email_address': email_address,
                        'dedup_key': dedup_key,
                    }, on_conflict='user_id,dedup_key')
                    if hasattr(res, 'execute'):
                        res.execute()
                    logger.info(f"Price match credit row inserted: {order_number} - ${amount_saved} - {product_name or 'Unknown'}")
                except Exception as e:
                    logger.warning(f"Price match credit upsert for {order_number}: {e}")

            # Aggregate totals and update orders
            for order_number, order in affected_orders.items():
                try:
                    # Sum all credit rows for this order
                    credits_result = (client.table('order_price_match_credits')
                                      .select('amount_saved')
                                      .eq('user_id', self.user_uid)
                                      .eq('order_id', order['id'])
                                      .execute())

                    total_saved = sum(float(r['amount_saved']) for r in (credits_result.data or []))

                    current_pm_status = order.get('pm_status')

                    # Don't overwrite active/completed pm_status or pm_amount_saved
                    if current_pm_status in ('queued', 'in_progress', 'completed'):
                        logger.info(f"Price match credit: Order {order_number} has pm_status={current_pm_status}, credit rows saved but order not updated")
                        continue

                    update_data = {
                        'pm_status': 'email_credit',
                        'pm_amount_saved': total_saved,
                        'pm_updated_at': datetime.now(timezone.utc).isoformat(),
                    }
                    client.table('orders').update(update_data).eq('id', order['id']).execute()
                    logger.info(f"Price match credit aggregated: Order {order_number} - total ${total_saved}")
                    self.stats['updated_orders'] += 1
                except Exception as e:
                    logger.error(f"Error aggregating credits for {order_number}: {e}")

        except Exception as e:
            logger.error(f"Error applying price match credits: {e}")

    def _get_search_criteria_with_date(self, criteria_source: dict, criteria_key: str, date_filter: Optional[str]) -> dict:
        criteria = copy.deepcopy(criteria_source.get(criteria_key, {}))
        if date_filter:
            criteria['date'] = f'after:{date_filter}'
        return criteria
