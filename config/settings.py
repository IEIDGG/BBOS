"""
Configuration settings for the Best Buy Order Tracker application.
"""

# Email server configurations
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

# Email search criteria
universal_date = "2024/12/01"
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
        'subject': '(OR (SUBJECT "Enjoy 1 month free of Game Pass Ultimate with your Best Buy purchase.") (SUBJECT "Your recent purchase came with a free gift."))',
        'date': 'after:2024/01/01'
    }
}

# Database settings
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
                email_date TEXT,
                order_number TEXT
            )
        '''
    }
}

# Output settings
OUTPUT_SETTINGS = {
    'csv_filename': 'bestbuy_orders.csv',
    'xbox_filename': 'xbox_codes.csv'
}
