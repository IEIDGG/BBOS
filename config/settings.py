EMAIL_SERVERS = {
    'gmail': {
        'server': 'imap.gmail.com',
        'port': 993,
        'use_ssl': True
    },
    'proton': {
        'server': '127.0.0.1',
        'port': 1143,
        'use_ssl': False
    },
    'icloud': {
        'server': 'imap.mail.me.com',
        'port': 993,
        'use_ssl': True
    }
}

universal_date = "2025/01/01"
SEARCH_CRITERIA = {
    'confirmation': {
        'from': '(OR (FROM "BestBuyInfo@emailinfo.bestbuy.com") (FROM "BestBuyInfo"))',
        'subject': 'SUBJECT "Thanks for your order"',
        'date': f'after:{universal_date}'
    },
    'cancellation': {
        'subject': 'OR SUBJECT "Your Best Buy order has been canceled" SUBJECT "Your order has been canceled"',
        'date': f'after:{universal_date}'
    },
    'shipped': {
        'subject': '(OR (SUBJECT "Your order will be shipped soon!") (SUBJECT "We have your tracking number."))',
        'date': f'after:{universal_date}'
    },
    'xbox': {
        'from': '(OR (FROM "BestBuyInfo@emailinfo.bestbuy.com") (FROM "BestBuyInfo"))',
        'subject': '(OR (SUBJECT "Enjoy 1 month free of Game Pass Ultimate with your Best Buy purchase.") (SUBJECT "Enjoy your recent shopping perks.") (SUBJECT "Your recent purchase came with a free gift."))',
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
    # TODO: Implement Amazon search criteria
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

DB_SETTINGS = {
    'filename': 'bestbuy_orders.sqlite3',
    'tables': {
        'orders': '''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                email_address TEXT
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
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                title TEXT,
                quantity TEXT,
                tracking_number TEXT
            )
        ''',
        'xbox_codes': '''
            CREATE TABLE IF NOT EXISTS xbox_codes (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE,
                email_date TEXT
            )
        '''
    }
}

AMAZON_DB_SETTINGS = {
    'filename': 'amazon_orders.sqlite3',
    'tables': {
        'orders': '''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                email_address TEXT
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
                order_number TEXT PRIMARY KEY,
                order_date TEXT,
                total_price TEXT,
                status TEXT,
                title TEXT,
                quantity TEXT,
                tracking_number TEXT
            )
        '''
    }
}

OUTPUT_SETTINGS = {
    'enable_output': False,
    'csv_filename': 'bestbuy_orders.csv',
    'xbox_filename': 'xbox_codes.csv'
}

# TODO: Add Amazon-specific output settings
AMAZON_OUTPUT_SETTINGS = {
    'enable_output': False,
    'csv_filename': 'amazon_orders.csv',
    'gift_cards_filename': 'amazon_gift_cards.csv'
}
