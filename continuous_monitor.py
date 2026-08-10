#!/usr/bin/env python3

import time
from datetime import datetime, timedelta
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
            criteria["date"] = f"after:{self.monitoring_date}"
        return criteria

    def process_confirmation_emails(self, folder: str):
        print(f"\nProcessing confirmation emails in folder: {folder}")

        dynamic_criteria = self._get_dynamic_search_criteria("confirmation")
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
            if result.get("order_number"):
                orders.append(
                    {
                        "date": result["date"],
                        "number": result["order_number"],
                        "status": "",
                        "tracking": [],
                        "products": result["products"],
                        "total_price": result["total_price"],
                        "email_address": result["email_address"],
                    }
                )
                self.statistics["confirmations"] += 1
                print(f"Processed confirmation: Order {result['order_number']}")

            self._update_stats(bool(result.get("order_number")))

        return orders

    def process_cancellation_emails(self, folder: str, orders):
        print(f"\nProcessing cancellation emails in folder: {folder}")

        dynamic_criteria = self._get_dynamic_search_criteria("cancellation")
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success:
            return

        print(f"Found {len(messages)} cancellation emails")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_cancellation_email(email_data)
            if result.get("order_number"):
                for order in orders:
                    if order["number"] == result["order_number"]:
                        order["status"] = "Cancelled"
                        self.statistics["cancellations"] += 1
                        print(f"Processed cancellation: Order {result['order_number']}")
                        break

            self._update_stats(bool(result.get("order_number")))

    def process_shipped_emails(self, folder: str, orders, db_manager=None):
        print(f"\nProcessing shipped emails in folder: {folder}")

        dynamic_criteria = self._get_dynamic_search_criteria("shipped")
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success:
            return

        print(f"Found {len(messages)} shipped emails")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_shipped_email(email_data)
            if result.get("order_number"):
                for order in orders:
                    if order["number"] == result["order_number"]:
                        order["status"] = "Shipped"
                        existing_tracking = order.get("tracking", [])
                        new_tracking = result["tracking_numbers"]

                        combined_tracking = list(set(existing_tracking + new_tracking))
                        order["tracking"] = combined_tracking

                        if "address_info" in result and db_manager:
                            state_code = result["address_info"]
                            order["state"] = state_code
                            db_manager.update_order_address(
                                result["order_number"], state_code
                            )
                            print(f"  State: {state_code}")

                        self.statistics["shipped"] += 1
                        self.statistics["tracking_numbers"] += len(
                            result["tracking_numbers"]
                        )
                        print(f"Processed shipped: Order {result['order_number']}")
                        break

            self._update_stats(bool(result.get("order_number")))

    def check_cancellation_emails(
        self, folder: str, existing_orders: List[Dict]
    ) -> List[str]:
        cancelled_orders = []

        dynamic_criteria = self._get_dynamic_search_criteria("cancellation")
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success or not messages:
            return cancelled_orders

        print(f"Checking {len(messages)} cancellation emails...")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_cancellation_email(email_data)
            if result.get("order_number"):
                order_num = result["order_number"]
                order_exists = any(
                    order.get("number") == order_num
                    or order.get("order_number") == order_num
                    for order in existing_orders
                )
                if order_exists and order_num not in cancelled_orders:
                    cancelled_orders.append(order_num)
                    self.statistics["cancellations"] += 1

            self._update_stats(bool(result.get("order_number")))

        return cancelled_orders

    def check_shipped_emails(
        self, folder: str, existing_orders: List[Dict]
    ) -> Dict[str, Dict]:
        shipped_orders = {}

        dynamic_criteria = self._get_dynamic_search_criteria("shipped")
        success, messages = self.connector.search_emails(folder, dynamic_criteria)

        if not success or not messages:
            return shipped_orders

        print(f"Checking {len(messages)} shipped emails...")

        for msg_id in messages:
            success, email_data = self.connector.fetch_email(msg_id)
            if not success:
                continue

            result = self.processor.process_shipped_email(email_data)
            if result.get("order_number"):
                order_num = result["order_number"]
                order_exists = any(
                    order.get("number") == order_num
                    or order.get("order_number") == order_num
                    for order in existing_orders
                )
                if order_exists:
                    tracking_numbers = result.get("tracking_numbers", [])
                    if tracking_numbers:
                        if order_num not in shipped_orders:
                            shipped_orders[order_num] = {
                                "tracking": [],
                                "address_info": None,
                            }
                        shipped_orders[order_num]["tracking"].extend(tracking_numbers)
                        shipped_orders[order_num]["tracking"] = list(
                            set(shipped_orders[order_num]["tracking"])
                        )
                        if "address_info" in result and result["address_info"]:
                            shipped_orders[order_num]["address_info"] = result[
                                "address_info"
                            ]
                        self.statistics["shipped"] += 1
                        self.statistics["tracking_numbers"] += len(tracking_numbers)

            self._update_stats(bool(result.get("order_number")))

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
        self._load_submitted_tracking_keys()

    def start_continuous_monitoring(self, folder: str) -> None:
        print("\n" + "=" * 60)
        print("        CONTINUOUS MONITORING MODE ACTIVATED")
        print("         Press Ctrl+C to stop monitoring")
        print("=" * 60)

        self.monitoring_active = True

        try:
            while self.monitoring_active:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n[{current_time}] Checking for new orders...")

                new_orders_found = False

                try:
                    new_orders_found = self.check_for_new_orders(folder)
                except Exception as e:
                    print(f"Error during monitoring check: {str(e)}")

                if not new_orders_found:
                    print("No new orders detected.")

                try:
                    self.submit_recent_trackings()
                except Exception as e:
                    print(f"Error submitting recent trackings: {str(e)}")

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
            order_handler = MonitoringOrderHandler(
                self.email_connector, self.monitoring_start_date
            )

            orders = order_handler.process_confirmation_emails(folder)
            new_orders = []

            if orders:
                for order in orders:
                    if order.get("number") not in self.processed_orders:
                        new_orders.append(order)
                        self.processed_orders.add(order.get("number"))

                if new_orders:
                    print(f"\n🎉 FOUND {len(new_orders)} NEW CONFIRMATION ORDER(S)!")
                    for order in new_orders:
                        print(
                            f"  📦 Order #{order.get('number')} - ${order.get('total_price', 'N/A')}"
                        )
                    new_orders_found = True

            all_orders = self.get_all_existing_orders()

            cancellation_updates = order_handler.check_cancellation_emails(
                folder, all_orders
            )
            cancelled_orders_to_save = []
            if cancellation_updates:
                print(f"\n❌ FOUND {len(cancellation_updates)} ORDER CANCELLATION(S)!")
                for order_num in cancellation_updates:
                    print(f"  🚫 Order #{order_num} - CANCELLED")

                    full_order = None
                    if self.output_handler and getattr(
                        self.output_handler, "db_manager", None
                    ):
                        full_order = self.output_handler.db_manager.get_order_by_number(
                            order_num
                        )

                    if full_order:
                        full_order["status"] = "Cancelled"
                        cancelled_orders_to_save.append(full_order)
                new_orders_found = True

            shipped_updates = order_handler.check_shipped_emails(folder, all_orders)
            shipped_orders_to_save = []
            if shipped_updates:
                print(f"\n🚚 FOUND {len(shipped_updates)} ORDER SHIPMENT(S)!")
                for order_num, shipped_data in shipped_updates.items():
                    tracking = shipped_data.get("tracking", [])
                    print(
                        f"  📮 Order #{order_num} - SHIPPED (Tracking: {', '.join(tracking)})"
                    )

                    full_order = None
                    if self.output_handler and getattr(
                        self.output_handler, "db_manager", None
                    ):
                        full_order = self.output_handler.db_manager.get_order_by_number(
                            order_num
                        )

                    if full_order:
                        full_order["status"] = "Shipped"
                        existing_tracking = full_order.get("tracking", [])
                        combined_tracking = list(set(existing_tracking + tracking))
                        full_order["tracking"] = combined_tracking
                        address_info = shipped_data.get("address_info")
                        if address_info:
                            full_order["state"] = address_info
                            if self.output_handler and getattr(
                                self.output_handler, "db_manager", None
                            ):
                                self.output_handler.db_manager.update_order_address(
                                    order_num, address_info
                                )
                            print(f"  State: {address_info}")
                        shipped_orders_to_save.append(full_order)
                new_orders_found = True

            if self.output_handler:
                if new_orders:
                    self.output_handler.save_orders(new_orders)

                if cancelled_orders_to_save:
                    self.output_handler.save_orders(cancelled_orders_to_save)

                if shipped_orders_to_save:
                    self.output_handler.save_orders(shipped_orders_to_save)

                if new_orders or cancelled_orders_to_save or shipped_orders_to_save:
                    self.output_handler.finalize_database()

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
                order_handler.process_cancellation_emails(folder, orders)
                db_manager = (
                    self.output_handler.db_manager
                    if self.output_handler
                    and getattr(self.output_handler, "db_manager", None)
                    else None
                )
                order_handler.process_shipped_emails(folder, orders, db_manager)

                for order in orders:
                    self.processed_orders.add(order.get("number"))
                print(f"Baseline established: {len(orders)} existing orders found")
                if self.output_handler:
                    self.output_handler.save_orders(orders)
                    self.output_handler.finalize_database()
            else:
                print("Baseline established: No existing orders found")

            self.monitoring_start_date = datetime.now().strftime("%Y/%m/%d")
            print(
                f"Future scans will only check emails from: {self.monitoring_start_date}"
            )

            print("\nProcessing baseline tracking submissions...")
            self.submit_recent_trackings(lookback_days=30)

            print("\nStarting continuous monitoring...")

            self.start_continuous_monitoring(folder)

        except Exception as e:
            print(f"Error starting continuous monitoring: {str(e)}")

    def stop_monitoring(self):
        self.monitoring_active = False

    def _load_submitted_tracking_keys(self) -> None:
        try:
            if self.output_handler and self.output_handler.db_manager:
                self.submitted_tracking_keys = (
                    self.output_handler.db_manager.get_submitted_tracking_keys()
                )
                print(
                    f"📋 Loaded {len(self.submitted_tracking_keys)} previously submitted tracking keys from database"
                )
            else:
                self.submitted_tracking_keys = set()
        except Exception as e:
            print(f"Warning: Could not load submitted tracking keys: {str(e)}")
            self.submitted_tracking_keys = set()

    def submit_recent_trackings(self, lookback_days: int = 3) -> None:
        if not self.api_config.is_enabled():
            return

        if not self.output_handler or not self.output_handler.db_manager:
            return

        try:
            now = datetime.now()
            end_date = now.strftime("%Y-%m-%d")
            lookback_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            print(
                f"Checking for orders with tracking between {lookback_date} and {end_date}"
            )
            orders_with_tracking = (
                self.output_handler.db_manager.get_orders_with_tracking_since_date(
                    lookback_date, end_date
                )
            )

            if not orders_with_tracking:
                return

            orders_to_submit = []

            for order in orders_with_tracking:
                tracking_numbers = order.get("tracking", [])
                if not tracking_numbers:
                    continue

                order_number = order.get("number") or order.get("order_number")
                if not order_number:
                    continue

                filtered_tracking = []
                for tracking_num in tracking_numbers:
                    unique_key = f"{order_number}_{tracking_num}"
                    if not self.output_handler.db_manager.is_tracking_key_submitted(
                        unique_key
                    ):
                        filtered_tracking.append(tracking_num)

                if filtered_tracking:
                    order_data = order.copy()
                    order_data["tracking"] = filtered_tracking
                    orders_to_submit.append(order_data)

            if orders_to_submit:
                total_tracking_numbers = sum(
                    len(order.get("tracking", [])) for order in orders_to_submit
                )
                print(
                    f"\n📡 Submitting {total_tracking_numbers} tracking number(s) from {len(orders_to_submit)} order(s) between {lookback_date} and {end_date} (Bulk API)..."
                )

                result = self.api_submitter.submit_orders_bulk(orders_to_submit)

                if result.get("success"):
                    submitted_count = result.get("total_submitted", 0)
                    if submitted_count > 0:
                        submitted_keys = []
                        for order in orders_to_submit:
                            order_number = order.get("number") or order.get(
                                "order_number"
                            )
                            for tracking_num in order.get("tracking", []):
                                unique_key = f"{order_number}_{tracking_num}"
                                submitted_keys.append(
                                    {
                                        "tracking_key": unique_key,
                                        "order_number": order_number,
                                        "tracking_number": tracking_num,
                                    }
                                )

                        if submitted_keys:
                            self.output_handler.db_manager.add_submitted_tracking_keys_batch(
                                submitted_keys
                            )
                            self.submitted_tracking_keys.update(
                                key["tracking_key"] for key in submitted_keys
                            )
                            print(
                                f"💾 Saved {len(submitted_keys)} submitted tracking keys to database"
                            )

                    print(f"✅ Bulk Submission: {result['message']}")
                    print(f"   Total submitted: {submitted_count}")
                    print(f"   Total failed: {result.get('total_failed', 0)}")
                    print(f"   Buying groups: {result.get('buying_groups', 0)}")

                    for group_result in result.get("group_results", []):
                        buying_group = group_result.get("buying_group")
                        successful = group_result.get("successful", 0)
                        failed = group_result.get("failed", 0)
                        skipped = group_result.get("skipped", 0)
                        print(
                            f"   • {buying_group}: {successful} successful, {failed} failed, {skipped} skipped"
                        )
                else:
                    print(f"⚠️ Bulk Submission: {result['message']}")
            else:
                print("   No new trackings to submit (all already submitted)")

        except Exception as e:
            print(f"❌ Error submitting recent trackings: {str(e)}")
            import traceback

            traceback.print_exc()
