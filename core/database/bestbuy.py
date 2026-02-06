import logging
from typing import Dict
from .base import BaseDatabaseManager
from config.settings import DB_SETTINGS

logger = logging.getLogger(__name__)


class BestBuyDatabaseManager(BaseDatabaseManager):
    def __init__(self, email: str = None):
        super().__init__(DB_SETTINGS, email=email, service='bestbuy')

    def insert_order(self, order: Dict) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()

        try:
            self._ensure_column('orders', 'state')
            self._ensure_column('orders', 'website')
            
            cursor.execute('SELECT * FROM orders WHERE order_number = ?', (order['number'],))
            existing_order = cursor.fetchone()

            state_value = order.get('state', '')
            website_value = order.get('website', 'BestBuy')
            
            if existing_order:
                cursor.execute('''
                    UPDATE orders 
                    SET order_date = ?, total_price = ?, status = ?, email_address = ?, state = ?, website = ?
                    WHERE order_number = ?
                ''', (order['date'], order['total_price'], order['status'],
                     order['email_address'], state_value, website_value, order['number']))
            else:
                cursor.execute('''
                    INSERT INTO orders (order_number, order_date, total_price, status, email_address, state, website)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (order['number'], order['date'], order['total_price'],
                     order['status'], order['email_address'], state_value, website_value))

            order_id = order['number']

            cursor.execute('DELETE FROM products WHERE order_id = ?', (order_id,))
            cursor.execute('DELETE FROM tracking_numbers WHERE order_id = ?', (order_id,))

            for product in order['products']:
                cursor.execute('''
                    INSERT INTO products (order_id, title, price, quantity)
                    VALUES (?, ?, ?, ?)
                ''', (order_id, product['title'], product['price'], product['quantity']))

            for tracking_number in order['tracking']:
                cursor.execute('''
                    INSERT INTO tracking_numbers (order_id, tracking_number)
                    VALUES (?, ?)
                ''', (order_id, tracking_number))

            self.connection.commit()

        except Exception as e:
            logger.error(f"Error inserting order {order['number']}: {str(e)}")
            print(f"Error inserting order {order['number']}: {str(e)}")
            self.connection.rollback()

    def insert_xbox_code(self, code_data: Dict) -> None:
        if not self.connection:
            return

        if 'xbox_codes' not in self.db_config['tables']:
            logger.warning("Xbox codes table not available in this database configuration")
            print("Xbox codes table not available in this database configuration")
            return

        cursor = self.connection.cursor()
        try:
            self._ensure_column('xbox_codes', 'email_address')
            
            cursor.execute('''
                INSERT OR IGNORE INTO xbox_codes (code, email_date, email_address)
                VALUES (?, ?, ?)
            ''', (code_data['code'], code_data['date'], code_data.get('email_address')))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error inserting Xbox code: {str(e)}")
            print(f"Error inserting Xbox code: {str(e)}")
            self.connection.rollback()

