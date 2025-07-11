#!/usr/bin/env python3

import sys
import os
from typing import Optional, Dict, Any

from core.profile_manager import ProfileManager
from core.utils import get_db_settings
from email_processing.connector import EmailConnector
from email_processing.handlers import OrderEmailHandler, XboxEmailHandler
from output.file_handlers import OutputHandler


class BBOSApplication:
    def __init__(self):
        self.profile_manager = ProfileManager()
        self.output_handler = None
        self.email_connector = None
        self.current_profile = None
        self.selected_service = None

    def display_banner(self):
        print("\n" + "="*60)
        print("        BBOS - Multi-Platform Order Scraper")
        print("    Advanced Order Management & Processing System")
        print("          Best Buy | Amazon | Multi-Service")
        print("="*60)

    def select_service(self) -> Optional[str]:
        print("\nSelect Service to Process:")
        print("="*30)
        print("1. Best Buy")
        print("2. Amazon")
        print("3. Both Services")
        print("q. Cancel")
        
        while True:
            choice = input("\nSelect service (1-3) or 'q' to cancel: ").strip().lower()
            
            if choice == 'q':
                return None
            elif choice == '1':
                return 'bestbuy'
            elif choice == '2':
                return 'amazon'
            elif choice == '3':
                return 'both'
            else:
                print("Please enter a valid choice (1-3) or 'q' to cancel")

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
                email=profile['email'],
                password=profile['password'],
                service_type=profile['service']
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

            if self.current_profile and self.current_profile.get('service') == 'proton':
                default_folder = "All Mail"
                default_msg = "All Mail"
            else:
                default_folder = "INBOX"
                default_msg = "INBOX"

            print("\nAvailable email folders:")
            print("="*30)
            for i, folder in enumerate(folders, 1):
                print(f"{i}. {folder}")

            while True:
                try:
                    choice = input(f"\nSelect folder (1-{len(folders)}) or press Enter for {default_msg}: ").strip()
                    
                    if not choice:
                        return default_folder
                    
                    idx = int(choice)
                    if 1 <= idx <= len(folders):
                        return folders[idx - 1]
                    else:
                        print(f"Please enter a number between 1 and {len(folders)}")
                except ValueError:
                    print("Please enter a valid number")
        except Exception as e:
            print(f"Error selecting folder: {str(e)}")
            if self.current_profile and self.current_profile.get('service') == 'proton':
                return "All Mail"
            else:
                return "INBOX"

    def process_bestbuy_orders(self, folder: str) -> None:
        try:
            print(f"\nProcessing Best Buy orders from folder: {folder}")
            print("="*50)
            
            order_handler = OrderEmailHandler(self.email_connector)
            
            orders = order_handler.process_confirmation_emails(folder)
            
            if orders:
                order_handler.process_cancellation_emails(folder, orders)
                order_handler.process_shipped_emails(folder, orders)
                
                self.output_handler.save_orders(orders)
                self.output_handler.display_order_summary(order_handler.get_statistics())
            else:
                print("No Best Buy orders found to process")
                
        except Exception as e:
            print(f"Error processing Best Buy orders: {str(e)}")

    def process_amazon_orders(self, folder: str) -> None:
        # TODO: Implement Amazon order processing
        print(f"\nProcessing Amazon orders from folder: {folder}")
        print("="*50)
        print("TODO: Amazon order processing not yet implemented")
        print("Features to implement:")
        print("- Amazon email parser (similar to bb_parser.py)")
        print("- Amazon search criteria in settings.py")
        print("- Amazon-specific email handlers")
        print("- Amazon order confirmation email processing")
        print("- Amazon cancellation email processing")
        print("- Amazon shipped email processing")
        print("- Amazon tracking number extraction")

    def process_xbox_codes(self, folder: str) -> None:
        try:
            print(f"\nProcessing Xbox Game Pass codes from folder: {folder}")
            print("="*50)
            
            xbox_handler = XboxEmailHandler(self.email_connector)
            xbox_codes = xbox_handler.process_xbox_emails(folder)
            
            if xbox_codes:
                self.output_handler.save_xbox_codes(xbox_codes)
                self.output_handler.display_xbox_summary(len(xbox_codes))
            else:
                print("No Xbox codes found")
                
        except Exception as e:
            print(f"Error processing Xbox codes: {str(e)}")

    def display_processing_menu(self) -> str:
        print("\nProcessing Options:")
        print("="*30)
        
        if self.selected_service == 'bestbuy':
            print("1. Process Best Buy Orders")
            print("2. Process Xbox Game Pass Codes")
            print("3. Process Both")
            print("4. Exit")
        elif self.selected_service == 'amazon':
            print("1. Process Amazon Orders")
            print("2. Process Amazon Gift Cards (TODO)")
            print("3. Process Both")
            print("4. Exit")
        elif self.selected_service == 'both':
            print("1. Process Best Buy Orders")
            print("2. Process Amazon Orders")
            print("3. Process Xbox Game Pass Codes")
            print("4. Process All")
            print("5. Exit")
        
        max_choice = 4 if self.selected_service in ['bestbuy', 'amazon'] else 5
        
        while True:
            choice = input(f"\nSelect processing option (1-{max_choice}): ").strip()
            if choice in [str(i) for i in range(1, max_choice + 1)]:
                return choice
            print(f"Please enter a valid option (1-{max_choice})")

    def run_processing(self, folder: str) -> None:
        while True:
            choice = self.display_processing_menu()
            
            if self.selected_service == 'bestbuy':
                if choice == '1':
                    self.process_bestbuy_orders(folder)
                elif choice == '2':
                    self.process_xbox_codes(folder)
                elif choice == '3':
                    self.process_bestbuy_orders(folder)
                    self.process_xbox_codes(folder)
                elif choice == '4':
                    break
                    
            elif self.selected_service == 'amazon':
                if choice == '1':
                    self.process_amazon_orders(folder)
                elif choice == '2':
                    print("TODO: Amazon gift card processing not yet implemented")
                elif choice == '3':
                    self.process_amazon_orders(folder)
                    print("TODO: Amazon gift card processing not yet implemented")
                elif choice == '4':
                    break
                    
            elif self.selected_service == 'both':
                if choice == '1':
                    self.process_bestbuy_orders(folder)
                elif choice == '2':
                    self.process_amazon_orders(folder)
                elif choice == '3':
                    self.process_xbox_codes(folder)
                elif choice == '4':
                    self.process_bestbuy_orders(folder)
                    self.process_amazon_orders(folder)
                    self.process_xbox_codes(folder)
                elif choice == '5':
                    break
            
            if choice not in ['4', '5']:
                continue_choice = input("\nProcess again? (y/n): ").strip().lower()
                if continue_choice not in ['y', 'yes']:
                    break

    def initialize_output_handler(self, service: str) -> None:
        try:
            if service == 'bestbuy':
                self.output_handler = OutputHandler()
            elif service == 'amazon':
                # TODO: Implement Amazon-specific output handler
                print("TODO: Amazon output handler needs to be implemented")
                print("- Use AMAZON_DB_SETTINGS for database configuration")
                print("- Create Amazon-specific CSV files")
                print("- Handle Amazon order data structure")
                # For now, create a basic output handler with default settings
                self.output_handler = OutputHandler()
            elif service == 'both':
                # TODO: Implement multi-service output handler
                print("TODO: Multi-service output handler needs to be implemented")
                print("- Handle both Best Buy and Amazon databases")
                print("- Separate CSV files for each service")
                print("- Combined reporting functionality")
                # For now, create a basic output handler with default settings
                self.output_handler = OutputHandler()
        except Exception as e:
            print(f"Error initializing output handler: {str(e)}")
            self.output_handler = OutputHandler()

    def run(self):
        try:
            self.display_banner()
            
            self.selected_service = self.select_service()
            if not self.selected_service:
                print("No service selected. Exiting...")
                return
            
            print(f"\nService selected: {self.selected_service.title()}")
            
            self.initialize_output_handler(self.selected_service)
            
            profile = self.get_profile()
            if not profile:
                print("No profile selected. Exiting...")
                return
            
            if not self.connect_to_email(profile):
                print("Failed to connect to email. Exiting...")
                return
            
            folder = self.select_email_folder()
            if not folder:
                print("No folder selected. Exiting...")
                return
            
            self.run_processing(folder)
            
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user")
        except Exception as e:
            print(f"\nUnexpected error: {str(e)}")
        finally:
            self.cleanup()

    def cleanup(self):
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