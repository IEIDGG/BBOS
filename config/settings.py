import os

EMAIL_SERVERS = {
    'gmail': {
        'server': 'imap.gmail.com',
        'port': 993,
        'use_ssl': True
    },
    'proton': {
        'server': os.getenv('PROTON_BRIDGE_HOST', '127.0.0.1'),
        'port': int(os.getenv('PROTON_BRIDGE_PORT', 1143)),
        'use_ssl': False
    },
    'icloud': {
        'server': 'imap.mail.me.com',
        'port': 993,
        'use_ssl': True
    }
}

CURRENT_VERSION = "2.1.0"
universal_date = "2025/11/01"
SEARCH_CRITERIA = {
    'confirmation': {
        'from': '(OR (FROM "BestBuyInfo@emailinfo.bestbuy.com") (FROM "BestBuyInfo"))',
        'subject': 'SUBJECT "Thanks for your order"',
        'date': f'after:{universal_date}'
    },
    'cancellation': {
        'subject': '(OR (SUBJECT "Your Best Buy order has been canceled") (SUBJECT "An item has been cancelled from your order.") (SUBJECT "Your order has been cancelled.") (SUBJECT "We received your cancellation request."))',
        'date': f'after:{universal_date}'
    },
    'shipped': {
        'subject': f'(OR (SUBJECT "📦 Your package is out for delivery. 📦") (SUBJECT "Your order will be shipped soon!") (SUBJECT "We have your tracking number.") (SUBJECT "📦 Your package is on its way. 📦"))',
        'date': f'after:{universal_date}'
    },
    'xbox': {
        'from': '',
        'subject': '(OR (SUBJECT "Enjoy 1 month free of Game Pass Ultimate with your Best Buy purchase.") (SUBJECT "Enjoy your recent shopping perks.") (SUBJECT "Enjoy your recent shopping perk.") (SUBJECT "Your recent purchase came with a free gift."))',
        'date': f'after:{universal_date}'
    }
}

# TODO: Add Amazon search criteria
# 
# Amazon Implementation Requirements:
# 1. Create AMAZON_SEARCH_CRITERIA similar to SEARCH_CRITERIA above
# 2. Add Amazon email addresses and subject patterns:
#    - Confirmation emails: ship-confirm@amazon.com, auto-confirm@amazon.com
#    - Cancellation emails: Various cancellation subjects
#    - Shipped emails: ship-confirm@amazon.com with tracking info
#    - Gift card emails: gc-orders@amazon.com
# 3. Create amazon_parser.py in email_processing/parsers/
# 4. Update email_processing/handlers.py to include Amazon handlers
# 5. Modify output/file_handlers.py to support Amazon CSV format
# 6. Add Amazon-specific output settings to OUTPUT_SETTINGS

AMAZON_SEARCH_CRITERIA = {
    'confirmation': {
        'from': '(OR (FROM "ship-confirm@amazon.com") (FROM "auto-confirm@amazon.com"))',
        'subject': 'SUBJECT "Your order of"',
        'date': f'after:{universal_date}'
    },
    'cancellation': {
        'subject': 'OR SUBJECT "Your Amazon.com order has been canceled" SUBJECT "Canceled:"',
        'date': f'after:{universal_date}'
    },
    'shipped': {
        'from': 'FROM "ship-confirm@amazon.com"',
        'subject': 'SUBJECT "Your package has shipped"',
        'date': f'after:{universal_date}'
    },
    'gift_cards': {
        'from': 'FROM "gc-orders@amazon.com"',
        'subject': 'SUBJECT "Your Amazon.com Gift Card order"',
        'date': f'after:{universal_date}'
    }
}

COSTCO_SEARCH_CRITERIA = {
    'confirmation': {
        'from': 'FROM "orderstatus@costco.com"',
        'subject': 'SUBJECT "Your Costco.com Order Number" SUBJECT "is Confirmed"',
        'date': f'after:{universal_date}'
    },
    'cancellation': {
        'from': 'FROM "order-cancel@costco.com"',
        'subject': 'SUBJECT "Your Costco.com Order" SUBJECT "Was Cancelled"',
        'date': f'after:{universal_date}'
    },
    'shipped': {
        'from': '(OR (FROM "orderstatus@costco.com") (FROM "Costco@orders.costco.com") (FROM "orders.costco.com"))',
        'subject': '(OR (SUBJECT "Your Costco.com Order Number" SUBJECT "Was Shipped") (SUBJECT "has shipped"))',
        'date': f'after:{universal_date}'
    }
}

DB_SETTINGS = {
    'tables': {
        'orders': '''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                email_address TEXT,
                state TEXT,
                website TEXT DEFAULT 'BestBuy'
            )
        ''',
        'products': '''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                title TEXT,
                price TEXT,
                quantity TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'tracking_numbers': '''
            CREATE TABLE IF NOT EXISTS tracking_numbers (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                tracking_number TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'xbox_codes': '''
            CREATE TABLE IF NOT EXISTS xbox_codes (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE,
                email_date TEXT
            )
        ''',
        'successful_orders': '''
            CREATE TABLE IF NOT EXISTS successful_orders (
                website TEXT,
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                title TEXT,
                quantity TEXT,
                tracking_number TEXT,
                state TEXT,
                email_address TEXT
            )
        ''',
        'submitted_tracking_keys': '''
            CREATE TABLE IF NOT EXISTS submitted_tracking_keys (
                tracking_key TEXT PRIMARY KEY,
                order_number TEXT,
                tracking_number TEXT,
                submitted_date TEXT,
                FOREIGN KEY (order_number) REFERENCES orders (order_number)
            )
        '''
    }
}

AMAZON_DB_SETTINGS = {
    'tables': {
        'orders': '''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                email_address TEXT,
                state TEXT,
                website TEXT DEFAULT 'Amazon'
            )
        ''',
        'products': '''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                title TEXT,
                price TEXT,
                quantity TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'tracking_numbers': '''
            CREATE TABLE IF NOT EXISTS tracking_numbers (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                tracking_number TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'successful_orders': '''
            CREATE TABLE IF NOT EXISTS successful_orders (
                website TEXT,
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                title TEXT,
                quantity TEXT,
                tracking_number TEXT,
                state TEXT,
                email_address TEXT
            )
        ''',
        'submitted_tracking_keys': '''
            CREATE TABLE IF NOT EXISTS submitted_tracking_keys (
                tracking_key TEXT PRIMARY KEY,
                order_number TEXT,
                tracking_number TEXT,
                submitted_date TEXT,
                FOREIGN KEY (order_number) REFERENCES orders (order_number)
            )
        '''
    }
}

COSTCO_DB_SETTINGS = {
    'tables': {
        'orders': '''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                email_address TEXT,
                state TEXT,
                cancellation_date TEXT,
                website TEXT DEFAULT 'Costco'
            )
        ''',
        'products': '''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                title TEXT,
                item_number TEXT,
                price TEXT,
                quantity TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'tracking_numbers': '''
            CREATE TABLE IF NOT EXISTS tracking_numbers (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                tracking_number TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (order_number)
            )
        ''',
        'membership_numbers': '''
            CREATE TABLE IF NOT EXISTS membership_numbers (
                id INTEGER PRIMARY KEY,
                membership_number TEXT UNIQUE,
                email_address TEXT,
                first_seen_date TEXT
            )
        ''',
        'successful_orders': '''
            CREATE TABLE IF NOT EXISTS successful_orders (
                website TEXT,
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                title TEXT,
                quantity TEXT,
                tracking_number TEXT,
                state TEXT,
                email_address TEXT,
                membership_number TEXT
            )
        ''',
        'submitted_tracking_keys': '''
            CREATE TABLE IF NOT EXISTS submitted_tracking_keys (
                tracking_key TEXT PRIMARY KEY,
                order_number TEXT,
                tracking_number TEXT,
                submitted_date TEXT,
                FOREIGN KEY (order_number) REFERENCES orders (order_number)
            )
        '''
    }
}

OUTPUT_SETTINGS = {
    'enable_output': False,
    'csv_filename': 'bestbuy_orders.csv',
    'xbox_filename': 'bestbuy_xbox_codes.csv'
}

AMAZON_OUTPUT_SETTINGS = {
    'enable_output': False,
    'csv_filename': 'amazon_orders.csv',
    'gift_cards_filename': 'amazon_gift_cards.csv'
}

COSTCO_OUTPUT_SETTINGS = {
    'enable_output': False,
    'csv_filename': 'costco_orders.csv'
}

