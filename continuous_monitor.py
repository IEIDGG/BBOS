#!/usr/bin/env python3

import time
from datetime import datetime
from typing import Optional, Dict, Any, Set, List

from email_processing.handlers import OrderEmailHandler
from config.settings import SEARCH_CRITERIA
from api.submitter import OrderAPISubmitter, APIConfig


class MonitoringOrderHandler(OrderEmailHandler):
    def __init__(self, connector, monitoring_date=None):
        super().__init__(connector)
        self.monitoring_date = monitoring_date
    
    def _get_dynamic_search_criteria(self, email_type: str) -> Dict[str, Any]:
        criteria = SEARCH_CRITERIA[email_type].copy()
        if self.monitoring_date:
            criteria['date'] = f'after:{self.monitoring_date}'
        return criteria
    
    def process_confirmation_emails(self, folder: str):
        print(f"\nProcessing confirmation emails in folder: {folder}")
        
        dynamic_criteria = self._get_dynamic_search_criteria('confirmation')
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

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
    
    def process_cancellation_emails(self, folder: str, orders):
        print(f"\nProcessing cancellation emails in folder: {folder}")
        
        dynamic_criteria = self._get_dynamic_search_criteria('cancellation')
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

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
    
    def process_shipped_emails(self, folder: str, orders, db_manager=None):
        print(f"\nProcessing shipped emails in folder: {folder}")
        
        dynamic_criteria = self._get_dynamic_search_criteria('shipped')
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

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
                        existing_tracking = order.get('tracking', [])
                        new_tracking = result['tracking_numbers']
                        
                        combined_tracking = list(set(existing_tracking + new_tracking))
                        order['tracking'] = combined_tracking
                        
                        if 'address_info' in result and db_manager:
                            state_code = result['address_info']
                            order['state'] = state_code
                            db_manager.update_order_address(result['order_number'], state_code)
                            print(f"  State: {state_code}")
                        
                        self.statistics['shipped'] += 1
                        self.statistics['tracking_numbers'] += len(result['tracking_numbers'])
                        print(f"Processed shipped: Order {result['order_number']}")
                        break

            self._update_stats(bool(result.get('order_number')))

    def check_cancellation_emails(self, folder: str, existing_orders: List[Dict]) -> List[str]:
        cancelled_orders = []
        
        dynamic_criteria = self._get_dynamic_search_criteria('cancellation')
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success or not messages:
            return cancelled_orders

        print(f"Checking {len(messages)} cancellation emails...")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_cancellation_email(email_data)
            if result.get('order_number'):
                order_num = result['order_number']
                order_exists = any(order.get('number') == order_num or order.get('order_number') == order_num 
                                 for order in existing_orders)
                if order_exists and order_num not in cancelled_orders:
                    cancelled_orders.append(order_num)
                    self.statistics['cancellations'] += 1

            self._update_stats(bool(result.get('order_number')))

        return cancelled_orders

    def check_shipped_emails(self, folder: str, existing_orders: List[Dict]) -> Dict[str, List[str]]:
        shipped_orders = {}
        
        dynamic_criteria = self._get_dynamic_search_criteria('shipped')
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success or not messages:
            return shipped_orders

        print(f"Checking {len(messages)} shipped emails...")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_shipped_email(email_data)
            if result.get('order_number'):
                order_num = result['order_number']
                order_exists = any(order.get('number') == order_num or order.get('order_number') == order_num 
                                 for order in existing_orders)
                if order_exists:
                    tracking_numbers = result.get('tracking_numbers', [])
                    if tracking_numbers:
                        if order_num not in shipped_orders:
                            shipped_orders[order_num] = []
                        shipped_orders[order_num].extend(tracking_numbers)
                        shipped_orders[order_num] = list(set(shipped_orders[order_num]))
                        self.statistics['shipped'] += 1
                        self.statistics['tracking_numbers'] += len(tracking_numbers)

            self._update_stats(bool(result.get('order_number')))

        return shipped_orders


class ContinuousMonitor:
    def __init__(self, email_connector, output_handler):
        self.email_connector = email_connector
        self.output_handler = output_handler
        self.monitoring_active = False
        self.processed_orders: Set[str] = set()
        self.monitoring_start_date = None
        self.api_config = APIConfig()
        self.api_submitter = OrderAPISubmitter(self.api_config)

    def start_continuous_monitoring(self, folder: str) -> None:
        print("\n" + "="*60)
        print("        CONTINUOUS MONITORING MODE ACTIVATED")
        print("    Attempting IMAP IDLE for real-time notifications...")
        print("         Press Ctrl+C to stop monitoring")
        print("="*60)
        
        self.monitoring_active = True
        idle_supported = True
        idle_failures = 0
        
        try:
            while self.monitoring_active:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if idle_supported:
                    print(f"\n[{current_time}] Waiting for new emails (IDLE)...")
                    idle_result = self.email_connector.idle_wait(folder, timeout=30)
                    
                    if idle_result is None:
                        idle_failures += 1
                        if idle_failures >= 3:
                            print("IDLE not supported or unreliable. Falling back to polling mode.")
                            idle_supported = False
                            continue
                        else:
                            print("IDLE attempt failed, retrying...")
                            time.sleep(2)
                            continue
                    
                    if idle_result:
                        print(f"\n[{current_time}] New email detected! Checking for orders...")
                        try:
                            self.check_for_new_orders(folder)
                        except Exception as e:
                            print(f"Error during monitoring check: {str(e)}")
                    else:
                        print("No new emails in the last 30 seconds.")
                    idle_failures = 0
                else:
                    print(f"\n[{current_time}] Checking for new orders...")
                    
                    new_orders_found = False
                    
                    try:
                        new_orders_found = self.check_for_new_orders(folder)
                    except Exception as e:
                        print(f"Error during monitoring check: {str(e)}")
                    
                    if not new_orders_found:
                        print("No new orders detected.")
                    
                    if self.monitoring_active:
                        print("Next check in 30 seconds... (Press Ctrl+C to stop)")
                        for i in range(30):
                            if not self.monitoring_active:
                                break
                            time.sleep(1)
                        
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        finally:
            self.monitoring_active = False

    def check_for_new_orders(self, folder: str) -> bool:
        new_orders_found = False
        
        try:
            order_handler = MonitoringOrderHandler(self.email_connector, self.monitoring_start_date)
            
            orders = order_handler.process_confirmation_emails(folder)
            new_orders = []
            
            if orders:
                for order in orders:
                    if order.get('number') not in self.processed_orders:
                        new_orders.append(order)
                        self.processed_orders.add(order.get('number'))
                
                if new_orders:
                    print(f"\n🎉 FOUND {len(new_orders)} NEW CONFIRMATION ORDER(S)!")
                    for order in new_orders:
                        print(f"  📦 Order #{order.get('number')} - ${order.get('total_price', 'N/A')}")
                    new_orders_found = True
            
            all_orders = self.get_all_existing_orders()
            
            cancellation_updates = order_handler.check_cancellation_emails(folder, all_orders)
            if cancellation_updates:
                print(f"\n❌ FOUND {len(cancellation_updates)} ORDER CANCELLATION(S)!")
                for order_num in cancellation_updates:
                    print(f"  🚫 Order #{order_num} - CANCELLED")
                new_orders_found = True
            
            shipped_updates = order_handler.check_shipped_emails(folder, all_orders)
            if shipped_updates:
                print(f"\n🚚 FOUND {len(shipped_updates)} ORDER SHIPMENT(S)!")
                for order_num, tracking in shipped_updates.items():
                    print(f"  📮 Order #{order_num} - SHIPPED (Tracking: {', '.join(tracking)})")
                new_orders_found = True
                
                if self.api_config.is_enabled():
                    self._submit_shipped_orders_to_api(shipped_updates, all_orders)
            
            if new_orders:
                self.output_handler.save_orders(new_orders)
                    
        except Exception as e:
            print(f"Error checking for new orders: {str(e)}")
        
        return new_orders_found

    def get_all_existing_orders(self) -> List[Dict]:
        try:
            if self.output_handler and self.output_handler.db_manager:
                return self.output_handler.db_manager.get_all_orders()
            return []
        except Exception as e:
            print(f"Error getting existing orders: {str(e)}")
            return []

    def run_continuous_monitoring(self, folder: str) -> None:
        print("\nInitializing continuous monitoring...")
        
        try:
            print("Performing initial scan to establish baseline...")
            order_handler = OrderEmailHandler(self.email_connector)
            orders = order_handler.process_confirmation_emails(folder)
            
            if orders:
                for order in orders:
                    self.processed_orders.add(order.get('number'))
                print(f"Baseline established: {len(orders)} existing orders found")
            
            self.monitoring_start_date = datetime.now().strftime("%Y/%m/%d")
            print(f"Future scans will only check emails from: {self.monitoring_start_date}")
            
            self.start_continuous_monitoring(folder)
            
        except Exception as e:
            print(f"Error starting continuous monitoring: {str(e)}")

    def stop_monitoring(self):
        self.monitoring_active = False
    
    def _submit_shipped_orders_to_api(self, shipped_updates: Dict[str, List[str]], all_orders: List[Dict]) -> None:
        try:
            orders_to_submit = []
            total_tracking_numbers = 0
            
            for order_num, tracking_numbers in shipped_updates.items():
                matching_order = None
                for order in all_orders:
                    if order.get('number') == order_num or order.get('order_number') == order_num:
                        matching_order = order
                        break
                
                if matching_order:
                    order_data = matching_order.copy()
                    order_data['tracking'] = tracking_numbers
                    orders_to_submit.append(order_data)
                    total_tracking_numbers += len(tracking_numbers)
            
            if orders_to_submit:
                if total_tracking_numbers > 1:
                    print(f"\n📡 Bulk submitting {total_tracking_numbers} tracking number(s) from {len(orders_to_submit)} order(s) to API...")
                    result = self.api_submitter.submit_orders_bulk(orders_to_submit)
                    
                    if result.get('success'):
                        print(f"✅ Bulk Submission: {result['message']}")
                        for group_result in result.get('group_results', []):
                            buying_group = group_result.get('buying_group')
                            successful = group_result.get('successful', 0)
                            failed = group_result.get('failed', 0)
                            skipped = group_result.get('skipped', 0)
                            print(f"   • {buying_group}: {successful} successful, {failed} failed, {skipped} skipped")
                    else:
                        print(f"⚠️ Bulk Submission: {result['message']}")
                else:
                    print(f"\n📡 Submitting {total_tracking_numbers} tracking number to API...")
                    result = self.api_submitter.submit_orders(orders_to_submit)
                    
                    if result.get('success'):
                        print(f"✅ API Submission: {result['message']}")
                    else:
                        print(f"⚠️ API Submission: {result['message']}")
                
        except Exception as e:
            print(f"❌ Error submitting to API: {str(e)}")
