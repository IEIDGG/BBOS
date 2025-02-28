# it's in the directory
import argparse
from typing import Optional, Dict
from core.profile_manager import ProfileManager
from email_processing.connector import EmailConnector
from email_processing.handlers import OrderEmailHandler, XboxEmailHandler
from output.file_handlers import OutputHandler


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Best Buy Order Tracker with profile management"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="orders",
        choices=["orders", "xbox", "all"],
        help="Mode to run. 'orders' processes order emails; 'xbox' processes Xbox emails; 'all' does both.",
    )
    parser.add_argument(
        "--manage-profiles",
        action="store_true",
        help="Manage profiles instead of processing emails",
    )
    return parser.parse_args()


def process_orders(email_connector: EmailConnector, folder: str) -> tuple[list, dict]:
    """Process order-related emails."""
    handler = OrderEmailHandler(email_connector)
    orders = handler.process_confirmation_emails(folder)
    handler.process_cancellation_emails(folder, orders)
    handler.process_shipped_emails(folder, orders)
    return orders, handler.get_statistics()


def process_xbox_codes(email_connector: EmailConnector, folder: str) -> list:
    """Process Xbox code emails."""
    handler = XboxEmailHandler(email_connector)
    return handler.process_xbox_emails(folder)


def ensure_profile_exists(profile_manager: ProfileManager) -> Optional[Dict]:
    """Ensure at least one profile exists and return a selected profile."""
    profile = profile_manager.select_profile()

    if not profile:
        print("\nNo profiles found. Let's create one now.")
        if profile_manager.add_profile():
            # Try selecting profile again after creation
            profile = profile_manager.select_profile()

    return profile


def main(manage_profiles_override: bool = None):
    """Main application entry point.

    If manage_profiles_override is provided (True/False), it overrides the command-line flag.
    """
    args = parse_arguments()
    if manage_profiles_override is not None:
        args.manage_profiles = manage_profiles_override

    profile_manager = ProfileManager()

    # Handle profile management
    if args.manage_profiles:
        profile_manager.manage_profiles()
        return

    # Get profile selection or create new profile if none exist
    profile = ensure_profile_exists(profile_manager)
    if not profile:
        print("Unable to proceed without a valid profile.")
        return

    email_connector = None
    output_handler = None

    try:
        # Initialize email connector with profile credentials
        # Use the appropriate identifier based on service type
        login_id = profile['username'] if profile['service'] == 'icloud' else profile['email']
        email_connector = EmailConnector(
            login_id,
            profile['password'],
            profile['service']
        )

        # Connect to email server
        email_connector.connect()

        # Initialize output handler
        output_handler = OutputHandler()

        # Determine folder based on service type
        folder = '"All Mail"' if profile['service'] == 'proton' else 'INBOX'
        print(f"\nProcessing emails for profile: {profile['name']}")

        # Process based on selected mode
        if args.mode in ['orders', 'all']:
            orders, stats = process_orders(email_connector, folder)
            output_handler.save_orders(orders)
            output_handler.display_order_summary(stats)

        if args.mode in ['xbox', 'all']:
            xbox_codes = process_xbox_codes(email_connector, folder)
            if xbox_codes:
                output_handler.save_xbox_codes(xbox_codes)
                output_handler.display_xbox_summary(len(xbox_codes))

    except Exception as e:
        print(f"\nError running application: {str(e)}")

    finally:
        # Clean up resources
        if email_connector:
            email_connector.disconnect()
        if output_handler:
            output_handler.close()


if __name__ == "__main__":
    main()
    exit(0)
