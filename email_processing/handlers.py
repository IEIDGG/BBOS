import logging
import re
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import email
from .connector import EmailConnector
from .processor import EmailProcessor
from config.settings import (
    SEARCH_CRITERIA,
    COSTCO_SEARCH_CRITERIA,
    AMAZON_SEARCH_CRITERIA,
    WALMART_SEARCH_CRITERIA,
)

logger = logging.getLogger(__name__)


def get_search_criteria_with_date(
    criteria_key: str, date_filter: Optional[str] = None, criteria_source: dict = None
) -> dict:
    source = criteria_source if criteria_source else SEARCH_CRITERIA
    criteria = copy.deepcopy(source[criteria_key])
    if date_filter:
        criteria["date"] = f"after:{date_filter}"
    elif date_filter is None and "date" in criteria:
        pass
    return criteria


class BaseEmailHandler:
    def __init__(self, connector: EmailConnector):
        self.connector = connector
        self.processor = EmailProcessor()
        self.statistics = {"processed": 0, "successful": 0, "failed": 0}

    def _update_stats(self, success: bool) -> None:
        self.statistics["processed"] += 1
        if success:
            self.statistics["successful"] += 1
        else:
            self.statistics["failed"] += 1


class OrderEmailHandler(BaseEmailHandler):
    def __init__(self, connector: EmailConnector):
        super().__init__(connector)
        self.statistics.update(
            {
                "confirmations": 0,
                "cancellations": 0,
                "payment_declined": 0,
                "shipped": 0,
                "tracking_numbers": 0,
            }
        )

    def _get_cancellation_status(
        self, result: Dict, mark_payment_declined_as_cancelled: bool
    ) -> str:
        if result.get("cancellation_type") == "payment_declined":
            return (
                "Cancelled"
                if mark_payment_declined_as_cancelled
                else "Payment Declined"
            )
        return "Cancelled"

    def _apply_shipped_location(
        self, order: Dict, result: Dict, db_manager=None
    ) -> None:
        state = (result.get("state") or "").strip()
        zip_code = (result.get("zip") or "").strip()
        zip_and_state = (result.get("zip_and_state") or "").strip()
        address_info = (result.get("address_info") or "").strip()

        if not zip_and_state and address_info:
            zip_and_state = address_info

        if not state and zip_and_state:
            match = re.search(r"\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\b", zip_and_state)
            if match:
                state = match.group(1)
                if not zip_code:
                    zip_code = match.group(2)

        if state:
            order["state"] = state
        if zip_code:
            order["zip"] = zip_code
        if zip_and_state:
            order["zip_and_state"] = zip_and_state

        location = zip_and_state or (
            f"{state} {zip_code}".strip() if state or zip_code else ""
        )
        if location:
            print(f"  Location: {location}")
            logger.info(
                "Shipped location for %s: %s",
                result.get("order_number"),
                location,
            )
            if db_manager:
                db_manager.update_order_address(
                    result["order_number"],
                    zip_and_state or state,
                )

    def _apply_cancellation_result(
        self, result: Dict, orders: List[Dict], mark_payment_declined_as_cancelled: bool
    ) -> None:
        order_number = result.get("order_number")
        if not order_number:
            return

        status = self._get_cancellation_status(
            result, mark_payment_declined_as_cancelled
        )
        matched = False
        for order in orders:
            if order["number"] == order_number:
                if not (
                    result.get("cancellation_type") == "payment_declined"
                    and status == "Payment Declined"
                    and order.get("status") == "Cancelled"
                ):
                    order["status"] = status
                matched = True
                break

        if not matched:
            orders.append(
                {
                    "date": result.get("date", ""),
                    "number": order_number,
                    "status": status,
                    "status_reason": result.get("cancellation_type", ""),
                    "tracking": [],
                    "products": [],
                    "email_address": result.get("email_address", ""),
                    "website": "BestBuy",
                }
            )
        elif result.get("cancellation_type") == "payment_declined":
            for order in orders:
                if order["number"] == order_number:
                    order["status_reason"] = "payment_declined"
                    break

        if result.get("cancellation_type") == "payment_declined":
            self.statistics["payment_declined"] += 1
            print(f"Processed payment update: Order {order_number} -> {status}")
        else:
            self.statistics["cancellations"] += 1
            print(f"Processed cancellation: Order {order_number}")

    def process_confirmation_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing confirmation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date("confirmation", date_filter)
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return []

        print(f"Found {len(messages)} confirmation emails")
        orders = []

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_confirmation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            orders.append(
                                {
                                    "date": result["date"],
                                    "number": result["order_number"],
                                    "status": "",
                                    "tracking": [],
                                    "products": result["products"],
                                    "xbox_items": result.get("xbox_items", []),
                                    "item_image": result.get("item_image", ""),
                                    "total_price": result["total_price"],
                                    "email_address": result["email_address"],
                                    "order_details_link": result.get(
                                        "order_details_link", ""
                                    ),
                                    "state": result.get("state", ""),
                                    "zip": result.get("zip", ""),
                                    "zip_and_state": result.get("zip_and_state", ""),
                                    "estimated_delivery": result.get(
                                        "estimated_delivery", ""
                                    ),
                                    "website": "BestBuy",
                                }
                            )
                            self.statistics["confirmations"] += 1
                            location = result.get("zip_and_state") or result.get(
                                "state", ""
                            )
                            print(
                                f"Processed confirmation: Order {result['order_number']}"
                                + (f" ({location})" if location else "")
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        print(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
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
                            "xbox_items": result.get("xbox_items", []),
                            "item_image": result.get("item_image", ""),
                            "total_price": result["total_price"],
                            "email_address": result["email_address"],
                            "order_details_link": result.get("order_details_link", ""),
                            "state": result.get("state", ""),
                            "zip": result.get("zip", ""),
                            "zip_and_state": result.get("zip_and_state", ""),
                            "estimated_delivery": result.get("estimated_delivery", ""),
                            "website": "BestBuy",
                        }
                    )
                    self.statistics["confirmations"] += 1
                    location = result.get("zip_and_state") or result.get("state", "")
                    print(
                        f"Processed confirmation: Order {result['order_number']}"
                        + (f" ({location})" if location else "")
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

        return orders

    def process_cancellation_emails(
        self,
        folder: str,
        orders: List[Dict],
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
        mark_payment_declined_as_cancelled: bool = True,
    ) -> None:
        print(f"\nProcessing cancellation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date("cancellation", date_filter)
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} cancellation emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_cancellation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            self._apply_cancellation_result(
                                result, orders, mark_payment_declined_as_cancelled
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        print(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_cancellation_email(email_data)
                if result.get("order_number"):
                    self._apply_cancellation_result(
                        result, orders, mark_payment_declined_as_cancelled
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

    def process_shipped_emails(
        self,
        folder: str,
        orders: List[Dict],
        db_manager=None,
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing shipped emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date("shipped", date_filter)
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} shipped emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(self.processor.process_shipped_email, email_data): (
                        email_data,
                        idx,
                    )
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            matched = False
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    order["status"] = "Shipped"
                                    existing_tracking = order.get("tracking", [])
                                    new_tracking = result["tracking_numbers"]

                                    combined_tracking = list(
                                        set(existing_tracking + new_tracking)
                                    )
                                    order["tracking"] = combined_tracking
                                    self._apply_shipped_location(
                                        order, result, db_manager
                                    )

                                    self.statistics["shipped"] += 1
                                    self.statistics["tracking_numbers"] += len(
                                        result["tracking_numbers"]
                                    )
                                    print(
                                        f"Processed shipped: Order {result['order_number']}"
                                    )
                                    matched = True
                                    break

                            if not matched and result.get("tracking_numbers"):
                                new_order = {
                                    "number": result["order_number"],
                                    "status": "Shipped",
                                    "tracking": result["tracking_numbers"],
                                }
                                self._apply_shipped_location(
                                    new_order, result, db_manager
                                )
                                orders.append(new_order)
                                self.statistics["shipped"] += 1
                                self.statistics["tracking_numbers"] += len(
                                    result["tracking_numbers"]
                                )
                                print(
                                    f"Processed shipped: Order {result['order_number']} (from shipped email only)"
                                )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        print(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_shipped_email(email_data)
                if result.get("order_number"):
                    matched = False
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            order["status"] = "Shipped"
                            existing_tracking = order.get("tracking", [])
                            new_tracking = result["tracking_numbers"]

                            combined_tracking = list(
                                set(existing_tracking + new_tracking)
                            )
                            order["tracking"] = combined_tracking
                            self._apply_shipped_location(order, result, db_manager)

                            self.statistics["shipped"] += 1
                            self.statistics["tracking_numbers"] += len(
                                result["tracking_numbers"]
                            )
                            print(f"Processed shipped: Order {result['order_number']}")
                            self.connector.mark_uid_processed(msg_id)
                            matched = True
                            break

                    if not matched and result.get("tracking_numbers"):
                        new_order = {
                            "number": result["order_number"],
                            "status": "Shipped",
                            "tracking": result["tracking_numbers"],
                        }
                        self._apply_shipped_location(new_order, result, db_manager)
                        orders.append(new_order)
                        self.statistics["shipped"] += 1
                        self.statistics["tracking_numbers"] += len(
                            result["tracking_numbers"]
                        )
                        print(
                            f"Processed shipped: Order {result['order_number']} (from shipped email only)"
                        )
                        self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

    def process_price_match_credit_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing Best Buy price match credit emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "price_match_credit", date_filter
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return []

        print(f"Found {len(messages)} price match credit emails")
        credits = []

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_price_match_credit_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number") and result.get("amount_saved"):
                            credits.append(result)
                            print(
                                f"Processed price match credit: Order {result['order_number']} - ${result['amount_saved']}"
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        print(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_price_match_credit_email(email_data)
                if result.get("order_number") and result.get("amount_saved"):
                    credits.append(result)
                    print(
                        f"Processed price match credit: Order {result['order_number']} - ${result['amount_saved']}"
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

        return credits

    def get_statistics(self) -> Dict:
        return self.statistics

    def print_fetch_statistics(self) -> None:
        stats = self.connector.get_fetch_stats()
        print(f"\n=== Email Fetch Statistics ===")
        print(f"Total fetches: {stats['fetch_count']}")
        print(f"Remaining quota: {stats['remaining']}/{stats['max_fetches']}")
        print(f"Usage: {(stats['fetch_count'] / stats['max_fetches'] * 100):.1f}%")


class XboxEmailHandler(BaseEmailHandler):
    def process_xbox_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing Xbox Game Pass emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date("xbox", date_filter)
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            print("Failed to search for Xbox Game Pass emails")
            return []

        if not messages:
            print("No Xbox Game Pass emails found")
            return []

        print(f"Found {len(messages)} Xbox Game Pass emails")
        xbox_codes = []

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(self.processor.process_xbox_email, email_data): (
                        email_data,
                        idx,
                    )
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("code"):
                            xbox_codes.append(result)
                            print(f"Processed Xbox code: {result['code']}")

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("code")))
                    except Exception as e:
                        print(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success or not email_data:
                    print(f"Failed to fetch email ID: {msg_id}")
                    continue

                result = self.processor.process_xbox_email(email_data)
                if result.get("code"):
                    xbox_codes.append(result)
                    print(f"Processed Xbox code: {result['code']}")
                    self.connector.mark_uid_processed(msg_id)
                else:
                    print(f"No Xbox code found in email ID: {msg_id}")

                self._update_stats(bool(result.get("code")))

        return xbox_codes


class CostcoEmailHandler(BaseEmailHandler):
    def __init__(self, connector: EmailConnector):
        super().__init__(connector)
        self.statistics.update(
            {
                "confirmations": 0,
                "cancellations": 0,
                "shipped": 0,
                "tracking_numbers": 0,
            }
        )

    def process_confirmation_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing Costco confirmation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "confirmation", date_filter, COSTCO_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return []

        print(f"Found {len(messages)} Costco confirmation emails")
        orders = []

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_costco_confirmation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            orders.append(
                                {
                                    "date": result["date"],
                                    "number": result["order_number"],
                                    "status": "",
                                    "tracking": [],
                                    "products": result["products"],
                                    "item_image": result.get("item_image", ""),
                                    "total_price": result["total_price"],
                                    "email_address": result["email_address"],
                                    "membership_number": result.get(
                                        "membership_number", ""
                                    ),
                                    "state": result.get("state", ""),
                                    "website": "Costco",
                                }
                            )
                            self.statistics["confirmations"] += 1
                            print(f"✓ Costco CONFIRMED: Order {result['order_number']}")

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_costco_confirmation_email(email_data)
                if result.get("order_number"):
                    orders.append(
                        {
                            "date": result["date"],
                            "number": result["order_number"],
                            "status": "",
                            "tracking": [],
                            "products": result["products"],
                            "item_image": result.get("item_image", ""),
                            "total_price": result["total_price"],
                            "email_address": result["email_address"],
                            "membership_number": result.get("membership_number", ""),
                            "state": result.get("state", ""),
                            "website": "Costco",
                        }
                    )
                    self.statistics["confirmations"] += 1
                    print(f"✓ Costco CONFIRMED: Order {result['order_number']}")
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

        return orders

    def process_cancellation_emails(
        self,
        folder: str,
        orders: List[Dict],
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Costco cancellation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "cancellation", date_filter, COSTCO_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Costco cancellation emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_costco_cancellation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    order["status"] = "Cancelled"
                                    if result.get("cancellation_date"):
                                        order["cancellation_date"] = result[
                                            "cancellation_date"
                                        ]
                                    self.statistics["cancellations"] += 1
                                    print(
                                        f"✗ Costco CANCELLED: Order {result['order_number']}"
                                    )
                                    break

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_costco_cancellation_email(email_data)
                if result.get("order_number"):
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            order["status"] = "Cancelled"
                            if result.get("cancellation_date"):
                                order["cancellation_date"] = result["cancellation_date"]
                            self.statistics["cancellations"] += 1
                            print(f"✗ Costco CANCELLED: Order {result['order_number']}")
                            self.connector.mark_uid_processed(msg_id)
                            break

                self._update_stats(bool(result.get("order_number")))

    def process_shipped_emails(
        self,
        folder: str,
        orders: List[Dict],
        db_manager=None,
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Costco shipped emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "shipped", date_filter, COSTCO_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Costco shipped emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_costco_shipped_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    if order.get("status") == "Cancelled":
                                        logger.debug(
                                            f"Skipping shipped update for cancelled order: {result['order_number']}"
                                        )
                                        break
                                    order["status"] = "Shipped"
                                    existing_tracking = order.get("tracking", [])
                                    new_tracking = result.get("tracking_numbers", [])

                                    combined_tracking = list(
                                        set(existing_tracking + new_tracking)
                                    )
                                    order["tracking"] = combined_tracking

                                    self.statistics["shipped"] += 1
                                    self.statistics["tracking_numbers"] += len(
                                        new_tracking
                                    )
                                    tracking_display = (
                                        ", ".join(new_tracking)
                                        if new_tracking
                                        else "None"
                                    )
                                    print(
                                        f"📦 Costco SHIPPED: Order {result['order_number']} | Tracking: {tracking_display}"
                                    )
                                    break

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_costco_shipped_email(email_data)
                if result.get("order_number"):
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            if order.get("status") == "Cancelled":
                                logger.debug(
                                    f"Skipping shipped update for cancelled order: {result['order_number']}"
                                )
                                break
                            order["status"] = "Shipped"
                            existing_tracking = order.get("tracking", [])
                            new_tracking = result.get("tracking_numbers", [])

                            combined_tracking = list(
                                set(existing_tracking + new_tracking)
                            )
                            order["tracking"] = combined_tracking

                            self.statistics["shipped"] += 1
                            self.statistics["tracking_numbers"] += len(new_tracking)
                            tracking_display = (
                                ", ".join(new_tracking) if new_tracking else "None"
                            )
                            print(
                                f"📦 Costco SHIPPED: Order {result['order_number']} | Tracking: {tracking_display}"
                            )
                            self.connector.mark_uid_processed(msg_id)
                            break

                self._update_stats(bool(result.get("order_number")))

    def get_statistics(self) -> Dict:
        return self.statistics

    def print_fetch_statistics(self) -> None:
        stats = self.connector.get_fetch_stats()
        print(f"\n=== Email Fetch Statistics ===")
        print(f"Total fetches: {stats['fetch_count']}")
        print(f"Remaining quota: {stats['remaining']}/{stats['max_fetches']}")
        print(f"Usage: {(stats['fetch_count'] / stats['max_fetches'] * 100):.1f}%")


class AmazonEmailHandler(BaseEmailHandler):
    def __init__(self, connector: EmailConnector):
        super().__init__(connector)
        self.statistics.update(
            {
                "confirmations": 0,
                "cancellations": 0,
                "shipped": 0,
                "tracking_numbers": 0,
            }
        )

    def _split_order_by_items(self, result: Dict) -> List[Dict]:
        split_orders = []
        products = result.get("products", [])

        if not products:
            return []

        for product in products:
            asin = product.get("asin", "")

            if not asin:
                logger.debug(
                    f"Skipping product without ASIN in order {result['order_number']}"
                )
                continue

            split_orders.append(
                {
                    "date": result["date"],
                    "number": result["order_number"],
                    "status": "",
                    "tracking": [],
                    "tracking_with_links": [],
                    "products": [product],
                    "total_price": product.get("price", "N/A"),
                    "unit_price": product.get("unit_price", ""),
                    "quantity": product.get("quantity", "1"),
                    "asin": asin,
                    "email_address": result["email_address"],
                    "state": result.get("state", ""),
                    "website": "Amazon",
                }
            )
            logger.debug(
                f"Split order item: {result['order_number']} ASIN:{asin} - {product.get('title', '')[:50]}"
            )

        return split_orders

    def process_confirmation_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing Amazon confirmation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "confirmation", date_filter, AMAZON_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return []

        print(f"Found {len(messages)} Amazon confirmation emails")
        orders = []

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_amazon_confirmation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            split_items = self._split_order_by_items(result)
                            orders.extend(split_items)
                            self.statistics["confirmations"] += len(split_items)
                            print(
                                f"✓ Amazon CONFIRMED: Order {result['order_number']} ({len(split_items)} items split)"
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_amazon_confirmation_email(email_data)
                if result.get("order_number"):
                    split_items = self._split_order_by_items(result)
                    orders.extend(split_items)
                    self.statistics["confirmations"] += len(split_items)
                    print(
                        f"✓ Amazon CONFIRMED: Order {result['order_number']} ({len(split_items)} items split)"
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

        return orders

    def process_cancellation_emails(
        self,
        folder: str,
        orders: List[Dict],
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Amazon cancellation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "cancellation", date_filter, AMAZON_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Amazon cancellation emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_amazon_cancellation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    order["status"] = "Cancelled"
                                    self.statistics["cancellations"] += 1
                                    print(
                                        f"✗ Amazon CANCELLED: Order {result['order_number']}"
                                    )
                                    break

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_amazon_cancellation_email(email_data)
                if result.get("order_number"):
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            order["status"] = "Cancelled"
                            self.statistics["cancellations"] += 1
                            print(f"✗ Amazon CANCELLED: Order {result['order_number']}")
                            self.connector.mark_uid_processed(msg_id)
                            break

                self._update_stats(bool(result.get("order_number")))

    def _process_shipped_result(
        self, result: Dict, orders: List[Dict], db_manager=None
    ) -> int:
        if not result.get("order_number"):
            return 0

        order_number = result["order_number"]
        shipped_products = result.get("products", [])

        shipped_asins = {}
        for product in shipped_products:
            asin = product.get("asin", "")
            if asin:
                qty = int(product.get("quantity", 1))
                shipped_asins[asin] = shipped_asins.get(asin, 0) + qty

        matched_count = 0

        for order in orders:
            if order["number"] != order_number:
                continue

            if order.get("status") == "Cancelled":
                logger.debug(
                    f"Skipping shipped update for cancelled order: {order['number']}"
                )
                continue

            order_asin = order.get("asin", "")

            if (
                order_asin
                and order_asin in shipped_asins
                and shipped_asins[order_asin] > 0
            ):
                order_qty = int(order.get("quantity", 1))
                shipped_qty = shipped_asins[order_asin]

                if shipped_qty >= order_qty:
                    order["status"] = "Shipped"
                    order["shipped_quantity"] = str(order_qty)
                    shipped_asins[order_asin] -= order_qty
                else:
                    order["status"] = "Partially Shipped"
                    order["shipped_quantity"] = str(shipped_qty)
                    shipped_asins[order_asin] = 0

                if result.get("state") and db_manager:
                    order["state"] = result["state"]
                    db_manager.update_order_address(order["number"], result["state"])

                matched_count += 1
                logger.debug(
                    f"Matched shipped item: {order['number']} ASIN:{order_asin} - qty {order.get('shipped_quantity')}"
                )

            elif not order_asin:
                order["status"] = "Shipped"

                if not order.get("products") and shipped_products:
                    order["products"] = shipped_products

                if result.get("state") and db_manager:
                    order["state"] = result["state"]
                    db_manager.update_order_address(order["number"], result["state"])

                matched_count += 1

        return matched_count

    def process_shipped_emails(
        self,
        folder: str,
        orders: List[Dict],
        db_manager=None,
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Amazon shipped emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "shipped", date_filter, AMAZON_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Amazon shipped emails")

        if len(messages) > 10:
            print("Using batch fetching for efficiency...")
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            print("⚡ Using parallel processing for email parsing...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_amazon_shipped_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            matched_count = self._process_shipped_result(
                                result, orders, db_manager
                            )

                            self.statistics["shipped"] += matched_count
                            print(
                                f"📦 Amazon SHIPPED: Order {result['order_number']} ({matched_count} items)"
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_amazon_shipped_email(email_data)
                if result.get("order_number"):
                    matched_count = self._process_shipped_result(
                        result, orders, db_manager
                    )

                    self.statistics["shipped"] += matched_count
                    print(
                        f"📦 Amazon SHIPPED: Order {result['order_number']} ({matched_count} items)"
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

    def get_statistics(self) -> Dict:
        return self.statistics

    def print_fetch_statistics(self) -> None:
        stats = self.connector.get_fetch_stats()
        print(f"\n=== Email Fetch Statistics ===")
        print(f"Total fetches: {stats['fetch_count']}")
        print(f"Remaining quota: {stats['remaining']}/{stats['max_fetches']}")
        print(f"Usage: {(stats['fetch_count'] / stats['max_fetches'] * 100):.1f}%")


class WalmartEmailHandler(BaseEmailHandler):
    def __init__(self, connector: EmailConnector):
        super().__init__(connector)
        self.statistics.update(
            {
                "confirmations": 0,
                "cancellations": 0,
                "shipped": 0,
                "tracking_numbers": 0,
            }
        )

    def process_confirmation_emails(
        self, folder: str, ignore_cache: bool = False, date_filter: Optional[str] = None
    ) -> List[Dict]:
        print(f"\nProcessing Walmart confirmation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "confirmation", date_filter, WALMART_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return []

        print(f"Found {len(messages)} Walmart confirmation emails")
        orders = []

        if len(messages) > 10:
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_walmart_confirmation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            orders.append(
                                {
                                    "date": result["date"],
                                    "number": result["order_number"],
                                    "status": "",
                                    "tracking": [],
                                    "products": result.get("products", []),
                                    "total_price": result.get("total_price", "N/A"),
                                    "email_address": result.get("email_address", ""),
                                    "state": result.get("state", ""),
                                    "zip": result.get("zip", ""),
                                    "website": "Walmart",
                                }
                            )
                            self.statistics["confirmations"] += 1
                            print(
                                f"Processed Walmart confirmation: Order {result['order_number']}"
                            )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_walmart_confirmation_email(email_data)
                if result.get("order_number"):
                    orders.append(
                        {
                            "date": result["date"],
                            "number": result["order_number"],
                            "status": "",
                            "tracking": [],
                            "products": result.get("products", []),
                            "total_price": result.get("total_price", "N/A"),
                            "email_address": result.get("email_address", ""),
                            "state": result.get("state", ""),
                            "zip": result.get("zip", ""),
                            "website": "Walmart",
                        }
                    )
                    self.statistics["confirmations"] += 1
                    print(
                        f"Processed Walmart confirmation: Order {result['order_number']}"
                    )
                    self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

        return orders

    def process_cancellation_emails(
        self,
        folder: str,
        orders: List[Dict],
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Walmart cancellation emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "cancellation", date_filter, WALMART_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Walmart cancellation emails")

        if len(messages) > 10:
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_walmart_cancellation_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    order["status"] = "Cancelled"
                                    self.statistics["cancellations"] += 1
                                    print(
                                        f"Processed Walmart cancellation: Order {result['order_number']}"
                                    )
                                    break

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_walmart_cancellation_email(email_data)
                if result.get("order_number"):
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            order["status"] = "Cancelled"
                            self.statistics["cancellations"] += 1
                            print(
                                f"Processed Walmart cancellation: Order {result['order_number']}"
                            )
                            self.connector.mark_uid_processed(msg_id)
                            break

                self._update_stats(bool(result.get("order_number")))

    def process_shipped_emails(
        self,
        folder: str,
        orders: List[Dict],
        db_manager=None,
        ignore_cache: bool = False,
        date_filter: Optional[str] = None,
    ) -> None:
        print(f"\nProcessing Walmart shipped emails in folder: {folder}")

        use_uid_filter = not ignore_cache
        search_criteria = get_search_criteria_with_date(
            "shipped", date_filter, WALMART_SEARCH_CRITERIA
        )
        success, messages = self.connector.search_emails(
            folder, search_criteria, use_uid_filter=use_uid_filter
        )

        if not success:
            return

        print(f"Found {len(messages)} Walmart shipped emails")

        if len(messages) > 10:
            email_data_list = self.connector.fetch_emails_batch(
                messages, use_uid=use_uid_filter
            )

            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_data = {
                    executor.submit(
                        self.processor.process_walmart_shipped_email, email_data
                    ): (email_data, idx)
                    for idx, email_data in enumerate(email_data_list)
                    if email_data
                }

                for future in as_completed(future_to_data):
                    email_data, idx = future_to_data[future]
                    try:
                        result = future.result()
                        if result.get("order_number"):
                            matched = False
                            for order in orders:
                                if order["number"] == result["order_number"]:
                                    if order.get("status") == "Cancelled":
                                        break
                                    order["status"] = "Shipped"
                                    existing_tracking = order.get("tracking", [])
                                    new_tracking = result.get("tracking_numbers", [])
                                    order["tracking"] = list(
                                        set(existing_tracking + new_tracking)
                                    )

                                    if result.get("state") and not order.get("state"):
                                        order["state"] = result["state"]
                                    if result.get("zip") and not order.get("zip"):
                                        order["zip"] = result["zip"]

                                    self.statistics["shipped"] += 1
                                    self.statistics["tracking_numbers"] += len(
                                        new_tracking
                                    )
                                    print(
                                        f"Processed Walmart shipped: Order {result['order_number']}"
                                    )
                                    matched = True
                                    break

                            if not matched and result.get("tracking_numbers"):
                                orders.append(
                                    {
                                        "number": result["order_number"],
                                        "status": "Shipped",
                                        "tracking": result["tracking_numbers"],
                                        "products": result.get("products", []),
                                        "total_price": result.get("total_price", "N/A"),
                                        "email_address": result.get(
                                            "email_address", ""
                                        ),
                                        "state": result.get("state", ""),
                                        "zip": result.get("zip", ""),
                                        "website": "Walmart",
                                    }
                                )
                                self.statistics["shipped"] += 1
                                self.statistics["tracking_numbers"] += len(
                                    result["tracking_numbers"]
                                )
                                print(
                                    f"Processed Walmart shipped: Order {result['order_number']} (from shipped email only)"
                                )

                            if idx < len(messages):
                                self.connector.mark_uid_processed(messages[idx])

                        self._update_stats(bool(result.get("order_number")))
                    except Exception as e:
                        logger.error(f"Error processing email: {e}")
                        self._update_stats(False)
        else:
            for msg_id in messages:
                success, email_data = self.connector.fetch_email(
                    msg_id, use_uid=use_uid_filter
                )
                if not success:
                    continue

                result = self.processor.process_walmart_shipped_email(email_data)
                if result.get("order_number"):
                    matched = False
                    for order in orders:
                        if order["number"] == result["order_number"]:
                            if order.get("status") == "Cancelled":
                                break
                            order["status"] = "Shipped"
                            existing_tracking = order.get("tracking", [])
                            new_tracking = result.get("tracking_numbers", [])
                            order["tracking"] = list(
                                set(existing_tracking + new_tracking)
                            )

                            if result.get("state") and not order.get("state"):
                                order["state"] = result["state"]
                            if result.get("zip") and not order.get("zip"):
                                order["zip"] = result["zip"]

                            self.statistics["shipped"] += 1
                            self.statistics["tracking_numbers"] += len(new_tracking)
                            print(
                                f"Processed Walmart shipped: Order {result['order_number']}"
                            )
                            self.connector.mark_uid_processed(msg_id)
                            matched = True
                            break

                    if not matched and result.get("tracking_numbers"):
                        orders.append(
                            {
                                "number": result["order_number"],
                                "status": "Shipped",
                                "tracking": result["tracking_numbers"],
                                "products": result.get("products", []),
                                "total_price": result.get("total_price", "N/A"),
                                "email_address": result.get("email_address", ""),
                                "state": result.get("state", ""),
                                "zip": result.get("zip", ""),
                                "website": "Walmart",
                            }
                        )
                        self.statistics["shipped"] += 1
                        self.statistics["tracking_numbers"] += len(
                            result["tracking_numbers"]
                        )
                        print(
                            f"Processed Walmart shipped: Order {result['order_number']} (from shipped email only)"
                        )
                        self.connector.mark_uid_processed(msg_id)

                self._update_stats(bool(result.get("order_number")))

    def get_statistics(self) -> Dict:
        return self.statistics

    def print_fetch_statistics(self) -> None:
        stats = self.connector.get_fetch_stats()
        print(f"\n=== Email Fetch Statistics ===")
        print(f"Total fetches: {stats['fetch_count']}")
        print(f"Remaining quota: {stats['remaining']}/{stats['max_fetches']}")
        print(f"Usage: {(stats['fetch_count'] / stats['max_fetches'] * 100):.1f}%")
