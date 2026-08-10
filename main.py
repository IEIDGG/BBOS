#!/usr/bin/env python3

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from api.submitter import APIConfig, OrderAPISubmitter
from config.settings import CURRENT_VERSION
from continuous_monitor import ContinuousMonitor
from core.database import DatabaseManager
from core.profile_manager import ProfileManager
from core.updater import UpdateManager
from email_processing.connector import EmailConnector
from email_processing.handlers import (
    CostcoEmailHandler,
    OrderEmailHandler,
    XboxEmailHandler,
)
from output.file_handlers import OutputHandler


class BBOSApplication:
    def __init__(self):
        self.profile_manager = ProfileManager()
        self.updater = UpdateManager()
        self.output_handler = None
        self.email_connector = None
        self.current_profile = None
        self.selected_service = None
        self.continuous_monitor = None
        self.api_config = APIConfig()

    def display_banner(self):
        print("\n" + "=" * 60)
        print(f"        BBOS - Multi-Platform Order Scraper v{CURRENT_VERSION}")
        print("    Advanced Order Management & Processing System")
        print("          Best Buy | Amazon | Multi-Service")
        print("=" * 60)

    def select_service(self) -> Optional[str]:
        print("\nMain Menu:")
        print("=" * 30)
        print("1. Process Orders")
        print("2. Continuous Monitor (30s refresh)")
        print("3. Settings")
        print("4. Check for Updates")
        print("q. Cancel")

        while True:
            choice = input("\nEnter choice (1-4) or 'q': ").strip().lower()

            if choice == "q":
                return None
            elif choice == "1":
                return self._select_service_submenu()
            elif choice == "2":
                return "monitor"
            elif choice == "3":
                return "settings"
            elif choice == "4":
                return "update"
            else:
                print("Please enter a valid choice (1-4) or 'q' to cancel")

    def _select_service_submenu(self) -> Optional[str]:
        print("\nSelect Service to Process:")
        print("=" * 30)
        print("1. Best Buy")
        print("2. Amazon")
        print("3. Costco")
        print("4. All Services")
        print("b. Back")

        while True:
            choice = input("\nEnter choice (1-4) or 'b': ").strip().lower()

            if choice == "b":
                return self.select_service()
            elif choice == "1":
                return "bestbuy"
            elif choice == "2":
                return "amazon"
            elif choice == "3":
                return "costco"
            elif choice == "4":
                return "all"
            else:
                print("Please enter a valid choice (1-4) or 'b' to go back")

    def get_profile(self) -> Optional[Dict[str, Any]]:
        try:
            profile = self.profile_manager.select_profile()
            if profile:
                self.current_profile = profile
                print(f"\nSelected profile: {profile['name']}")
                return profile
            return None
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
            return None
        except Exception as e:
            print(f"Error selecting profile: {str(e)}")
            return None

    def connect_to_email(self, profile: Dict[str, Any]) -> bool:
        try:
            print(f"\nConnecting to {profile['service'].title()} email service...")
            self.email_connector = EmailConnector(
                email=profile["email"],
                password=profile["password"],
                service_type=profile["service"],
            )
            self.email_connector.connect()
            return True
        except Exception as e:
            print(f"Failed to connect to email: {str(e)}")
            return False

    def select_email_folder(self) -> Optional[str]:
        try:
            folders = self.email_connector.get_folders()
            if not folders:
                print("No email folders found")
                return None

            if self.current_profile and self.current_profile.get("service") == "proton":
                default_folder = "All Mail"
                default_msg = "All Mail"
            else:
                default_folder = "INBOX"
                default_msg = "INBOX"

            last_folder = None
            if self.current_profile:
                profile_name = self.current_profile.get("name")
                if profile_name:
                    last_folder = self.profile_manager.get_last_folder(profile_name)
                    if last_folder and last_folder in folders:
                        default_folder = last_folder
                        default_msg = last_folder

            print("\nAvailable email folders:")
            print("=" * 30)
            for i, folder in enumerate(folders, 1):
                print(f"{i}. {folder}")

            while True:
                try:
                    choice = input(
                        f"\nSelect folder (1-{len(folders)}) or press Enter for {default_msg}: "
                    ).strip()

                    if not choice:
                        selected_folder = default_folder
                    else:
                        idx = int(choice)
                        if 1 <= idx <= len(folders):
                            selected_folder = folders[idx - 1]
                        else:
                            print(f"Please enter a number between 1 and {len(folders)}")
                            continue

                    if self.current_profile:
                        profile_name = self.current_profile.get("name")
                        if profile_name:
                            self.profile_manager.save_last_folder(
                                profile_name, selected_folder
                            )

                    return selected_folder
                except ValueError:
                    print("Please enter a valid number")
        except Exception as e:
            print(f"Error selecting folder: {str(e)}")
            if self.current_profile and self.current_profile.get("service") == "proton":
                return "All Mail"
            else:
                return "INBOX"

    def process_bestbuy_orders(
        self, folder: str, ignore_cache: bool = False, date_filter: str = None
    ) -> None:
        try:
            print(f"\nProcessing Best Buy orders from folder: {folder}")
            print("=" * 50)

            order_handler = OrderEmailHandler(self.email_connector)

            orders = order_handler.process_confirmation_emails(
                folder, ignore_cache=ignore_cache, date_filter=date_filter
            )

            if not orders:
                print("No new confirmation emails found")
                if self.output_handler and self.output_handler.db_manager:
                    existing_order_numbers = (
                        self.output_handler.db_manager.get_all_orders()
                    )
                    if existing_order_numbers:
                        print(
                            f"Loading {len(existing_order_numbers)} existing orders from database for processing..."
                        )
                        orders = []
                        for order_data in existing_order_numbers:
                            full_order = (
                                self.output_handler.db_manager.get_order_by_number(
                                    order_data["number"]
                                )
                            )
                            if full_order:
                                orders.append(full_order)
                        if orders:
                            print(f"Loaded {len(orders)} orders with full details")
                        else:
                            print("No orders with full details found")
                    else:
                        print("No existing orders found in database")

            if orders:
                order_handler.process_cancellation_emails(
                    folder, orders, ignore_cache=ignore_cache, date_filter=date_filter
                )
                order_handler.process_shipped_emails(
                    folder,
                    orders,
                    self.output_handler.db_manager,
                    ignore_cache=ignore_cache,
                    date_filter=date_filter,
                )

                self.output_handler.save_orders(orders)
                self.output_handler.finalize_database()
                self.output_handler.display_order_summary(
                    order_handler.get_statistics()
                )
            else:
                print("No Best Buy orders found to process")

            order_handler.print_fetch_statistics()

        except Exception as e:
            print(f"Error processing Best Buy orders: {str(e)}")

    def process_amazon_orders(
        self, folder: str, ignore_cache: bool = False, date_filter: str = None
    ) -> None:
        print(f"\nProcessing Amazon orders from folder: {folder}")
        print("=" * 50)
        print("TODO: Amazon order processing not yet implemented")
        print("Features to implement:")
        print("- Amazon email parser (similar to bb_parser.py)")
        print("- Amazon search criteria in settings.py")
        print("- Amazon-specific email handlers")
        print("- Amazon order confirmation email processing")
        print("- Amazon cancellation email processing")
        print("- Amazon shipped email processing")
        print("- Amazon tracking number extraction")

    def process_costco_orders(
        self, folder: str, ignore_cache: bool = False, date_filter: str = None
    ) -> None:
        try:
            print(f"\nProcessing Costco orders from folder: {folder}")
            print("=" * 50)

            costco_handler = CostcoEmailHandler(self.email_connector)

            orders = costco_handler.process_confirmation_emails(
                folder, ignore_cache=ignore_cache, date_filter=date_filter
            )

            if not orders:
                print("No new Costco confirmation emails found")
                if self.output_handler and self.output_handler.db_manager:
                    existing_order_numbers = (
                        self.output_handler.db_manager.get_all_orders()
                    )
                    if existing_order_numbers:
                        print(
                            f"Loading {len(existing_order_numbers)} existing orders from database for processing..."
                        )
                        orders = []
                        for order_data in existing_order_numbers:
                            full_order = (
                                self.output_handler.db_manager.get_order_by_number(
                                    order_data["number"]
                                )
                            )
                            if full_order:
                                orders.append(full_order)
                        if orders:
                            print(f"Loaded {len(orders)} orders with full details")
                        else:
                            print("No orders with full details found")
                    else:
                        print("No existing orders found in database")

            if orders:
                costco_handler.process_cancellation_emails(
                    folder, orders, ignore_cache=ignore_cache, date_filter=date_filter
                )
                costco_handler.process_shipped_emails(
                    folder,
                    orders,
                    self.output_handler.db_manager if self.output_handler else None,
                    ignore_cache=ignore_cache,
                    date_filter=date_filter,
                )

                if self.output_handler:
                    self.output_handler.save_orders(orders)
                    self.output_handler.finalize_database()
                    self.output_handler.display_order_summary(
                        costco_handler.get_statistics()
                    )
            else:
                print("No Costco orders found to process")

            costco_handler.print_fetch_statistics()

        except Exception as e:
            print(f"Error processing Costco orders: {str(e)}")

    def process_xbox_codes(
        self, folder: str, ignore_cache: bool = False, date_filter: str = None
    ) -> None:
        try:
            print(f"\nProcessing Xbox Game Pass codes from folder: {folder}")
            print("=" * 50)

            xbox_handler = XboxEmailHandler(self.email_connector)
            xbox_codes = xbox_handler.process_xbox_emails(
                folder, ignore_cache=ignore_cache, date_filter=date_filter
            )

            if xbox_codes:
                self.output_handler.save_xbox_codes(xbox_codes)
                self.output_handler.display_xbox_summary(len(xbox_codes))
            else:
                print("No Xbox codes found")

            stats = self.email_connector.get_fetch_stats()
            print("\n=== Email Fetch Statistics ===")
            print(f"Total fetches: {stats['fetch_count']}")
            print(f"Remaining quota: {stats['remaining']}/{stats['max_fetches']}")
            print(f"Usage: {(stats['fetch_count'] / stats['max_fetches'] * 100):.1f}%")

        except Exception as e:
            print(f"Error processing Xbox codes: {str(e)}")

    def display_processing_menu(self) -> str:
        print("\nProcessing Options:")
        print("=" * 30)

        if self.selected_service == "bestbuy":
            print("1. Process Best Buy Orders")
            print("2. Process Xbox Game Pass Codes")
            print("3. Process Both")
            print("4. Exit")
            max_choice = 4
        elif self.selected_service == "amazon":
            print("1. Process Amazon Orders")
            print("2. Process Amazon Gift Cards (TODO)")
            print("3. Process Both")
            print("4. Exit")
            max_choice = 4
        elif self.selected_service == "costco":
            print("1. Process Costco Orders")
            print("2. Exit")
            max_choice = 2
        elif self.selected_service == "all":
            print("1. Process Best Buy Orders")
            print("2. Process Amazon Orders")
            print("3. Process Costco Orders")
            print("4. Process Xbox Game Pass Codes")
            print("5. Process All")
            print("6. Exit")
            max_choice = 6
        else:
            max_choice = 4

        while True:
            choice = input(f"\nSelect processing option (1-{max_choice}): ").strip()
            if choice in [str(i) for i in range(1, max_choice + 1)]:
                return choice
            print(f"Please enter a valid option (1-{max_choice})")

    def select_date_range(self) -> str:
        print("\nDate Range Options:")
        print("=" * 30)
        print("1. Last 7 days")
        print("2. Last 30 days")
        print("3. Last 60 days")
        print("4. Last 90 days")
        print("5. Last year")
        print("6. Custom days back")
        print("7. Custom date")
        print("8. All time (no date filter)")

        while True:
            choice = input("\nSelect date range (1-8): ").strip()

            if choice == "1":
                date_filter = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
                print(f"📅 Searching emails from: {date_filter}")
                return date_filter
            elif choice == "2":
                date_filter = (datetime.now() - timedelta(days=30)).strftime("%Y/%m/%d")
                print(f"📅 Searching emails from: {date_filter}")
                return date_filter
            elif choice == "3":
                date_filter = (datetime.now() - timedelta(days=60)).strftime("%Y/%m/%d")
                print(f"📅 Searching emails from: {date_filter}")
                return date_filter
            elif choice == "4":
                date_filter = (datetime.now() - timedelta(days=90)).strftime("%Y/%m/%d")
                print(f"📅 Searching emails from: {date_filter}")
                return date_filter
            elif choice == "5":
                date_filter = (datetime.now() - timedelta(days=365)).strftime(
                    "%Y/%m/%d"
                )
                print(f"📅 Searching emails from: {date_filter}")
                return date_filter
            elif choice == "6":
                while True:
                    try:
                        days = input("Enter number of days back: ").strip()
                        days_int = int(days)
                        if days_int <= 0:
                            print("Please enter a positive number")
                            continue
                        date_filter = (
                            datetime.now() - timedelta(days=days_int)
                        ).strftime("%Y/%m/%d")
                        print(f"📅 Searching emails from: {date_filter}")
                        return date_filter
                    except ValueError:
                        print("Please enter a valid number")
            elif choice == "7":
                while True:
                    custom_date = input("Enter date (YYYY/MM/DD): ").strip()
                    try:
                        datetime.strptime(custom_date, "%Y/%m/%d")
                        print(f"📅 Searching emails from: {custom_date}")
                        return custom_date
                    except ValueError:
                        print(
                            "Invalid date format. Please use YYYY/MM/DD (e.g., 2025/01/15)"
                        )
            elif choice == "8":
                print("📅 Searching all emails (no date filter)")
                return None
            else:
                print("Please enter a valid option (1-8)")

    def run_processing(self, folder: str) -> None:
        ignore_cache = False
        cache_choice = (
            input("\nIgnore cache (process all emails)? (y/n): ").strip().lower()
        )
        if cache_choice in ["y", "yes"]:
            ignore_cache = True
            print("⚠ Cache ignored: All matching emails will be processed.")

        last_choice = None
        date_filter = None

        while True:
            if last_choice:
                choice = last_choice
            else:
                choice = self.display_processing_menu()

            exit_choices = {"bestbuy": "4", "amazon": "4", "costco": "2", "all": "6"}
            exit_choice = exit_choices.get(self.selected_service, "4")
            if choice != exit_choice:
                date_filter = self.select_date_range()

            if self.selected_service == "bestbuy":
                if choice == "1":
                    self.process_bestbuy_orders(folder, ignore_cache, date_filter)
                elif choice == "2":
                    self.process_xbox_codes(folder, ignore_cache, date_filter)
                elif choice == "3":
                    self.process_bestbuy_orders(folder, ignore_cache, date_filter)
                    self.process_xbox_codes(folder, ignore_cache, date_filter)
                elif choice == "4":
                    break

            elif self.selected_service == "amazon":
                if choice == "1":
                    self.process_amazon_orders(folder, ignore_cache, date_filter)
                elif choice == "2":
                    print("TODO: Amazon gift card processing not yet implemented")
                elif choice == "3":
                    self.process_amazon_orders(folder, ignore_cache, date_filter)
                    print("TODO: Amazon gift card processing not yet implemented")
                elif choice == "4":
                    break

            elif self.selected_service == "costco":
                if choice == "1":
                    self.process_costco_orders(folder, ignore_cache, date_filter)
                elif choice == "2":
                    break

            elif self.selected_service == "all":
                if choice == "1":
                    self.process_bestbuy_orders(folder, ignore_cache, date_filter)
                elif choice == "2":
                    self.process_amazon_orders(folder, ignore_cache, date_filter)
                elif choice == "3":
                    self.process_costco_orders(folder, ignore_cache, date_filter)
                elif choice == "4":
                    self.process_xbox_codes(folder, ignore_cache, date_filter)
                elif choice == "5":
                    self.process_bestbuy_orders(folder, ignore_cache, date_filter)
                    self.process_amazon_orders(folder, ignore_cache, date_filter)
                    self.process_costco_orders(folder, ignore_cache, date_filter)
                    self.process_xbox_codes(folder, ignore_cache, date_filter)
                elif choice == "6":
                    break

            should_break = False
            if self.selected_service == "bestbuy" and choice == "4":
                should_break = True
            elif self.selected_service == "amazon" and choice == "4":
                should_break = True
            elif self.selected_service == "costco" and choice == "2":
                should_break = True
            elif self.selected_service == "all" and choice == "6":
                should_break = True

            if not should_break:
                continue_choice = input("\nProcess again? (y/n): ").strip().lower()
                if continue_choice in ["y", "yes"]:
                    last_choice = choice
                else:
                    break
            else:
                break

    def initialize_output_handler(self, service: str) -> None:
        try:
            email = None
            if self.current_profile:
                email = self.current_profile.get("email")

            if service == "bestbuy":
                self.output_handler = OutputHandler(email=email, service="bestbuy")
            elif service == "amazon":
                print("TODO: Amazon output handler needs to be implemented")
                print("- Use AMAZON_DB_SETTINGS for database configuration")
                print("- Create Amazon-specific CSV files")
                print("- Handle Amazon order data structure")
                self.output_handler = OutputHandler(email=email, service="amazon")
            elif service == "costco":
                self.output_handler = OutputHandler(email=email, service="costco")
            elif service == "all":
                print("Multi-service mode: Using Best Buy output handler as default")
                self.output_handler = OutputHandler(email=email, service="bestbuy")
        except Exception as e:
            print(f"Error initializing output handler: {str(e)}")
            email = None
            if self.current_profile:
                email = self.current_profile.get("email")
            self.output_handler = OutputHandler(email=email, service=service)

    def run_continuous_monitoring(self, folder: str) -> None:
        self.continuous_monitor = ContinuousMonitor(
            self.email_connector, self.output_handler
        )
        self.continuous_monitor.run_continuous_monitoring(folder)

    def test_api_submission(self) -> None:
        print("\n" + "=" * 60)
        print("              API TEST SUBMISSION")
        print("=" * 60)

        if not self.api_config.is_enabled():
            print("\n✗ API submission is currently DISABLED")
            print("  Please enable API submission first (option 1)")
            input("\nPress Enter to continue...")
            return

        api_url = self.api_config.get_api_url()
        print(f"\nTesting API submission to: {api_url}")
        print("\nSelect test type:")
        print("1. Test Single Order Submission (latest order)")
        print("2. Test Bulk Order Submission (latest 2 orders)")
        print("3. Test Bulk Order Submission (Custom DB)")
        print("4. Cancel")

        while True:
            test_choice = input("\nSelect option (1-4): ").strip()

            if test_choice == "4":
                return

            if test_choice not in ["1", "2", "3"]:
                print("Please enter a valid option (1-4)")
                continue

            try:
                if test_choice == "3":
                    api_submitter = OrderAPISubmitter(self.api_config)
                    api_submitter.run_interactive_bulk_test()
                    input("\nPress Enter to continue...")
                    return

                email = None
                if self.current_profile:
                    email = self.current_profile.get("email")
                db_manager = DatabaseManager(email=email, service="bestbuy")

                if test_choice == "1":
                    print("\nFetching latest order with tracking...")
                    orders = db_manager.get_latest_orders(
                        limit=1, with_tracking_only=True
                    )

                    if not orders:
                        print("\n✗ No orders with tracking numbers found in database")
                        input("\nPress Enter to continue...")
                        return

                    order = orders[0]
                    print(f"\n✓ Found order: {order['number']}")
                    print(f"  Date: {order['date']}")
                    print(f"  Status: {order['status']}")
                    print(f"  Tracking numbers: {len(order['tracking'])}")
                    print(f"  State: {order.get('state', 'N/A')}")

                    print("\nSubmitting to API...")
                    api_submitter = OrderAPISubmitter(self.api_config)
                    result = api_submitter.submit_order(order)

                    print("\n" + "-" * 60)
                    if result["success"]:
                        print("✓ Status: SUCCESS")
                        print(f"✓ Message: {result['message']}")
                        print(f"✓ Submitted: {result['submitted']} tracking number(s)")

                        if "results" in result:
                            print("\nDetailed Results:")
                            for res in result["results"]:
                                status_icon = "✓" if res["status"] == "success" else "✗"
                                print(
                                    f"  {status_icon} {res['tracking_number']}: {res['status']} - {res['message']}"
                                )
                    else:
                        print("✗ Status: FAILED")
                        print(f"✗ Message: {result['message']}")
                        print(f"✗ Submitted: {result['submitted']} tracking number(s)")

                        if "results" in result:
                            print("\nDetailed Results:")
                            for res in result["results"]:
                                print(
                                    f"  ✗ {res['tracking_number']}: {res['status']} - {res['message']}"
                                )
                    print("-" * 60)

                elif test_choice == "2":
                    print("\nFetching latest 2 orders with tracking...")
                    orders = db_manager.get_latest_orders(
                        limit=2, with_tracking_only=True
                    )

                    if not orders:
                        print("\n✗ No orders with tracking numbers found in database")
                        input("\nPress Enter to continue...")
                        return

                    if len(orders) < 2:
                        print(
                            f"\n⚠ Only {len(orders)} order(s) with tracking found. Testing with available order(s)..."
                        )

                    print(f"\n✓ Found {len(orders)} order(s):")
                    for order in orders:
                        print(
                            f"  - Order {order['number']}: {len(order['tracking'])} tracking number(s)"
                        )

                    print("\nSubmitting to API (bulk)...")
                    api_submitter = OrderAPISubmitter(self.api_config)
                    result = api_submitter.submit_orders_bulk(orders)

                    print("\n" + "-" * 60)
                    if result["success"]:
                        print("✓ Status: SUCCESS")
                        print(f"✓ Message: {result['message']}")
                        print(
                            f"✓ Total Submitted: {result['total_submitted']} tracking number(s)"
                        )
                        print(
                            f"✓ Total Failed: {result['total_failed']} tracking number(s)"
                        )
                        print(f"✓ Buying Groups: {result['buying_groups']}")

                        if "group_results" in result:
                            print("\nGroup Results:")
                            for group_res in result["group_results"]:
                                print(f"\n  Buying Group: {group_res['buying_group']}")
                                print(f"    Total: {group_res['total']}")
                                print(f"    Successful: {group_res['successful']}")
                                print(f"    Failed: {group_res['failed']}")
                                print(f"    Skipped: {group_res['skipped']}")
                                print(f"    Message: {group_res['message']}")
                    else:
                        print("✗ Status: FAILED")
                        print(f"✗ Message: {result['message']}")
                        print(
                            f"✗ Total Submitted: {result['total_submitted']} tracking number(s)"
                        )
                    print("-" * 60)

                db_manager.close()
                input("\nPress Enter to continue...")
                return

            except Exception as e:
                print(f"\n✗ Error during test: {str(e)}")
                import traceback

                traceback.print_exc()
                input("\nPress Enter to continue...")
                return

    def show_settings_menu(self) -> bool:
        while True:
            print("\n" + "=" * 60)
            print("                    SETTINGS MENU")
            print("=" * 60)

            api_status = "ENABLED" if self.api_config.is_enabled() else "DISABLED"
            api_url = self.api_config.get_api_url()

            print(f"\n1. Toggle API Submission (Currently: {api_status})")
            print(f"   API URL: {api_url}")
            print("2. Configure API Settings")
            print("3. Check API Health")
            print("4. Test API Submission")
            print("5. Back to Main Menu")

            choice = input("\nSelect option (1-5): ").strip()

            if choice == "1":
                current_status = self.api_config.is_enabled()
                new_status = not current_status
                self.api_config.set_enabled(new_status)
                status_text = "ENABLED" if new_status else "DISABLED"
                print(f"\n✓ API Submission is now {status_text}")
                if new_status:
                    print(
                        f"  Orders with tracking numbers will be submitted to: {api_url}"
                    )
                input("\nPress Enter to continue...")

            elif choice == "2":
                print("\n" + "=" * 60)
                print("              API CONFIGURATION")
                print("=" * 60)
                print("\nTo configure API settings, edit: api/api_config.json")
                print("\nAvailable settings:")
                print("  - api_url: FastAPI backend URL")
                print("  - api_key: Authentication key")
                print("  - enabled: Enable/disable submission")
                print("  - zip_to_buying_group: ZIP code mappings (priority)")
                print("  - state_to_buying_group: State code mappings (fallback)")
                print("\nSee api/README.md for detailed documentation")
                input("\nPress Enter to continue...")

            elif choice == "3":
                print("\n" + "=" * 60)
                print("              API HEALTH CHECK")
                print("=" * 60)
                print(f"\nChecking API at: {api_url}/health")
                print("Please wait...")

                api_submitter = OrderAPISubmitter(self.api_config)
                health_result = api_submitter.check_api_health()

                print("\n" + "-" * 60)
                if health_result["success"]:
                    print(f"✓ Status: {health_result['status'].upper()}")
                    print(f"✓ Database: {health_result['database'].upper()}")
                    print(f"✓ Message: {health_result['message']}")
                else:
                    print(f"✗ Status: {health_result['status'].upper()}")
                    print(f"✗ Database: {health_result['database'].upper()}")
                    print(f"✗ Message: {health_result['message']}")
                print("-" * 60)

                input("\nPress Enter to continue...")

            elif choice == "4":
                self.test_api_submission()

            elif choice == "5":
                return False

            else:
                print("Please enter a valid option (1-5)")

        return False

    def run(self):
        try:
            if not hasattr(self, "_update_checked"):
                self._update_checked = True
                print("Checking for updates...")
                is_avail, new_ver = self.updater.check_for_updates()
                if is_avail:
                    print("\n" + "!" * 60)
                    print(f"!!! NEW UPDATE AVAILABLE: v{new_ver} !!!")
                    print("!!! Select 'Check for Updates' in the menu to install !!!")
                    print("!" * 60 + "\n")
                    time.sleep(2)

            self.display_banner()

            self.selected_service = self.select_service()
            if not self.selected_service:
                print("No service selected. Exiting...")
                return

            if self.selected_service == "settings":
                self.show_settings_menu()
                return self.run()

            if self.selected_service == "update":
                print("\nChecking for updates...")
                is_avail, new_ver = self.updater.check_for_updates()
                if is_avail:
                    print(f"\nUpdate available: v{new_ver}")
                    if (
                        input("Do you want to update now? (y/n): ")
                        .lower()
                        .startswith("y")
                    ):
                        if self.updater.perform_update():
                            print(
                                "\nPlease restart the application to use the new version."
                            )
                            return
                else:
                    print("\nNo updates available. You are on the latest version.")
                    input("\nPress Enter to continue...")
                return self.run()

            profile = self.get_profile()
            if not profile:
                print("No profile selected. Exiting...")
                return

            if self.selected_service == "monitor":
                print("\nContinuous Monitoring Mode Selected")
                self.initialize_output_handler("bestbuy")
            else:
                print(f"\nService selected: {self.selected_service.title()}")
                self.initialize_output_handler(self.selected_service)

            if not self.connect_to_email(profile):
                print("Failed to connect to email. Exiting...")
                return

            folder = self.select_email_folder()
            if not folder:
                print("No folder selected. Exiting...")
                return

            if self.selected_service == "monitor":
                self.run_continuous_monitoring(folder)
            else:
                self.run_processing(folder)

        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user")
        except Exception as e:
            print(f"\nUnexpected error: {str(e)}")
        finally:
            self.cleanup()

    def cleanup(self):
        if self.continuous_monitor:
            self.continuous_monitor.stop_monitoring()
        if self.email_connector:
            self.email_connector.disconnect()
        if self.output_handler:
            self.output_handler.close()
        print("\nThank you for using BBOS!")


def main():
    app = BBOSApplication()
    app.run()


if __name__ == "__main__":
    main()
