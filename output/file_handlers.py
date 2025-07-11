import csv
from typing import List, Dict
from config.settings import OUTPUT_SETTINGS
from core.database import DatabaseManager


class OutputHandler:
    def __init__(self):
        self.db_manager = DatabaseManager()

    def save_orders(self, orders: List[Dict]) -> None:
        if OUTPUT_SETTINGS['enable_output']:
            try:
                with open(OUTPUT_SETTINGS['csv_filename'], 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = [
                        'order_number', 'order_date', 'total_price', 'status',
                        'email_address', 'products', 'tracking_numbers'
                    ]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

                    for order in orders:
                        products_str = '; '.join(
                            [f"{p['title']} (Qty: {p['quantity']}, Price: {p['price']})"
                             for p in order['products']]
                        )
                        writer.writerow({
                            'order_number': order['number'],
                            'order_date': order['date'],
                            'total_price': order['total_price'],
                            'status': order['status'],
                            'email_address': order['email_address'],
                            'products': products_str,
                            'tracking_numbers': ', '.join(order['tracking'])
                        })
                print(f"Orders saved to {OUTPUT_SETTINGS['csv_filename']}")
            except Exception as e:
                print(f"Error saving orders to CSV: {str(e)}")
        else:
            print("CSV output disabled in settings - skipping CSV save operations")

        try:
            for order in orders:
                self.db_manager.insert_order(order)
            self.db_manager.create_successful_orders_view()
            print("Orders saved to SQLite database successfully")
        except Exception as e:
            print(f"Error saving orders to database: {str(e)}")

    def save_xbox_codes(self, codes: List[Dict]) -> None:
        if OUTPUT_SETTINGS['enable_output']:
            try:
                with open(OUTPUT_SETTINGS['xbox_filename'], 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = ['code', 'date']
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
        if code_count > 0 and OUTPUT_SETTINGS['enable_output']:
            print(f"Codes have been saved to {OUTPUT_SETTINGS['xbox_filename']}")
        elif code_count > 0:
            print("CSV output disabled in settings - codes not saved to CSV")

    def close(self):
        if self.db_manager:
            self.db_manager.close()