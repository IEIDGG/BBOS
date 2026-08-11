import csv
from typing import Dict, List, Optional

from config.settings import (
    AMAZON_OUTPUT_SETTINGS,
    COSTCO_OUTPUT_SETTINGS,
    OUTPUT_SETTINGS,
)
from core.database import DatabaseManager


def get_output_settings(service: str = "bestbuy") -> Dict:
    if service.lower() == "costco":
        return COSTCO_OUTPUT_SETTINGS
    elif service.lower() == "amazon":
        return AMAZON_OUTPUT_SETTINGS
    else:
        return OUTPUT_SETTINGS


class OutputHandler:
    def __init__(self, email: Optional[str] = None, service: str = "bestbuy"):
        self.service = service
        self.output_settings = get_output_settings(service)
        self.db_manager = DatabaseManager(email=email, service=service)

    def save_orders(self, orders: List[Dict]) -> None:
        if self.output_settings.get("enable_output", False):
            try:
                csv_filename = self.output_settings.get(
                    "csv_filename", f"{self.service}_orders.csv"
                )
                with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
                    fieldnames = [
                        "order_number",
                        "order_date",
                        "total_price",
                        "status",
                        "email_address",
                        "products",
                        "tracking_numbers",
                    ]
                    if self.service == "costco":
                        fieldnames.append("membership_number")

                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

                    for order in orders:
                        products_str = "; ".join(
                            [
                                f"{p.get('title', 'N/A')} (Qty: {p.get('quantity', '1')}, Price: {p.get('price', 'N/A')})"
                                for p in order.get("products", [])
                            ]
                        )
                        row = {
                            "order_number": order.get("number", ""),
                            "order_date": order.get("date", ""),
                            "total_price": order.get("total_price", ""),
                            "status": order.get("status", ""),
                            "email_address": order.get("email_address", ""),
                            "products": products_str,
                            "tracking_numbers": ", ".join(order.get("tracking", [])),
                        }
                        if self.service == "costco":
                            row["membership_number"] = order.get(
                                "membership_number", ""
                            )
                        writer.writerow(row)
                print(f"Orders saved to {csv_filename}")
            except Exception as e:
                print(f"Error saving orders to CSV: {str(e)}")
        else:
            print("CSV output disabled in settings - skipping CSV save operations")

        try:
            for order in orders:
                self.db_manager.insert_order(order)

                if self.service == "costco" and order.get("membership_number"):
                    self.db_manager.insert_membership_number(
                        {
                            "membership_number": order["membership_number"],
                            "email_address": order.get("email_address", ""),
                            "date": order.get("date", ""),
                        }
                    )
            print("Orders saved to SQLite database successfully")
        except Exception as e:
            print(f"Error saving orders to database: {str(e)}")

    def save_xbox_codes(self, codes: List[Dict]) -> None:
        if OUTPUT_SETTINGS["enable_output"]:
            try:
                with open(
                    OUTPUT_SETTINGS["xbox_filename"], "w", newline="", encoding="utf-8"
                ) as csvfile:
                    fieldnames = ["code", "date"]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    for code in codes:
                        writer.writerow(code)
                print(f"Xbox codes saved to {OUTPUT_SETTINGS['xbox_filename']}")
            except Exception as e:
                print(f"Error saving Xbox codes to CSV: {str(e)}")
        else:
            print("CSV output disabled in settings - skipping CSV save operations")

        try:
            for code in codes:
                self.db_manager.insert_xbox_code(code)
            print("Xbox codes saved to SQLite database successfully")
        except Exception as e:
            print(f"Error saving Xbox codes to database: {str(e)}")

    def finalize_database(self) -> None:
        try:
            self.db_manager.create_successful_orders_view()
            print("Database finalized successfully")
        except Exception as e:
            print(f"Error finalizing database: {str(e)}")

    def display_order_summary(self, stats: Dict) -> None:
        print("\nOrder Processing Summary")
        print("=" * 30)
        print(f"Total emails processed: {stats['processed']}")
        print(f"Successfully processed: {stats['successful']}")
        print(f"Failed to process: {stats['failed']}")
        print(f"Confirmation emails: {stats['confirmations']}")
        print(f"Cancellation emails: {stats['cancellations']}")
        print(f"Shipped orders: {stats['shipped']}")
        print(f"Tracking numbers found: {stats['tracking_numbers']}")

        if self.db_manager:
            db_summary = self.db_manager.get_order_summary()
            if db_summary:
                print("\nDatabase Summary")
                print("=" * 30)
                print(f"Total unique orders: {db_summary[0]}")
                print(f"Total orders: {db_summary[1]}")
                print(f"Shipped orders: {db_summary[2]}")
                print(f"Total tracking numbers: {db_summary[3]}")

    def display_xbox_summary(self, code_count: int) -> None:
        print("\nXbox Code Processing Summary")
        print("=" * 30)
        print(f"Total Xbox codes found: {code_count}")
        if code_count > 0 and OUTPUT_SETTINGS["enable_output"]:
            print(f"Codes have been saved to {OUTPUT_SETTINGS['xbox_filename']}")
        elif code_count > 0:
            print("CSV output disabled in settings - codes not saved to CSV")

    def close(self):
        if self.db_manager:
            self.db_manager.close()
