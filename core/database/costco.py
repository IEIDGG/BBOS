import logging
from typing import Dict, List
from datetime import datetime
from .base import BaseDatabaseManager
from config.settings import COSTCO_DB_SETTINGS

logger = logging.getLogger(__name__)


class CostcoDatabaseManager(BaseDatabaseManager):
    def __init__(self, email: str = None):
        super().__init__(COSTCO_DB_SETTINGS, email=email, service='costco')

    def insert_order(self, order: Dict) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()

        try:
            self._ensure_column('orders', 'state')
            self._ensure_column('orders', 'website')
            self._ensure_column('orders', 'cancellation_date')
            
            cursor.execute('SELECT * FROM orders WHERE order_number = ?', (order['number'],))
            existing_order = cursor.fetchone()

            state_value = order.get('state', '')
            website_value = order.get('website', 'Costco')
            cancellation_date = order.get('cancellation_date', '')
            
            if existing_order:
                cursor.execute('''
                    UPDATE orders 
                    SET order_date = ?, total_price = ?, status = ?, email_address = ?, 
                        state = ?, website = ?, cancellation_date = ?
                    WHERE order_number = ?
                ''', (order['date'], order['total_price'], order['status'],
                     order['email_address'], state_value, website_value, 
                     cancellation_date, order['number']))
            else:
                cursor.execute('''
                    INSERT INTO orders (order_number, order_date, total_price, status, 
                                        email_address, state, website, cancellation_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (order['number'], order['date'], order['total_price'],
                     order['status'], order['email_address'], state_value, 
                     website_value, cancellation_date))

            order_id = order['number']

            cursor.execute('DELETE FROM products WHERE order_id = ?', (order_id,))
            cursor.execute('DELETE FROM tracking_numbers WHERE order_id = ?', (order_id,))

            cursor.execute("PRAGMA table_info(products)")
            product_columns = [row[1] for row in cursor.fetchall()]
            has_item_number = 'item_number' in product_columns

            for product in order.get('products', []):
                if has_item_number:
                    cursor.execute('''
                        INSERT INTO products (order_id, title, item_number, price, quantity)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (order_id, product.get('title', ''), product.get('item_number', ''),
                          product.get('price', ''), product.get('quantity', '1')))
                else:
                    cursor.execute('''
                        INSERT INTO products (order_id, title, price, quantity)
                        VALUES (?, ?, ?, ?)
                    ''', (order_id, product.get('title', ''), product.get('price', ''), 
                          product.get('quantity', '1')))

            for tracking_number in order.get('tracking', []):
                cursor.execute('''
                    INSERT INTO tracking_numbers (order_id, tracking_number)
                    VALUES (?, ?)
                ''', (order_id, tracking_number))

            self.connection.commit()

        except Exception as e:
            logger.error(f"Error inserting Costco order {order['number']}: {str(e)}")
            print(f"Error inserting Costco order {order['number']}: {str(e)}")
            self.connection.rollback()

    def insert_membership_number(self, membership_data: Dict) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='membership_numbers'")
            if not cursor.fetchone():
                table_sql = self.db_config['tables'].get('membership_numbers', '''
                    CREATE TABLE IF NOT EXISTS membership_numbers (
                        id INTEGER PRIMARY KEY,
                        membership_number TEXT UNIQUE,
                        email_address TEXT,
                        first_seen_date TEXT
                    )
                ''')
                cursor.executescript(table_sql)
                self.connection.commit()
                logger.info("Created membership_numbers table")
                print("Created membership_numbers table")
            
            cursor.execute('''
                INSERT OR IGNORE INTO membership_numbers (membership_number, email_address, first_seen_date)
                VALUES (?, ?, ?)
            ''', (membership_data['membership_number'], 
                  membership_data.get('email_address', ''), 
                  membership_data.get('date', datetime.now().strftime("%Y-%m-%d"))))
            self.connection.commit()
            logger.info(f"Stored membership number: {membership_data['membership_number']}")
            print(f"Stored membership number: {membership_data['membership_number']}")
        except Exception as e:
            logger.error(f"Error inserting membership number: {str(e)}")
            print(f"Error inserting membership number: {str(e)}")
            self.connection.rollback()

    def get_membership_numbers(self) -> List[Dict]:
        if not self.connection:
            return []

        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='membership_numbers'")
            if not cursor.fetchone():
                return []
            
            cursor.execute('SELECT membership_number, email_address, first_seen_date FROM membership_numbers')
            rows = cursor.fetchall()
            return [{'membership_number': row[0], 'email_address': row[1], 'first_seen_date': row[2]} for row in rows]
        except Exception as e:
            logger.error(f"Error getting membership numbers: {str(e)}")
            print(f"Error getting membership numbers: {str(e)}")
            return []

