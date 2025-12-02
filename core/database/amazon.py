import logging
from typing import Dict
from .base import BaseDatabaseManager
from config.settings import AMAZON_DB_SETTINGS

logger = logging.getLogger(__name__)


class AmazonDatabaseManager(BaseDatabaseManager):
    def __init__(self, email: str = None):
        super().__init__(AMAZON_DB_SETTINGS, email=email, service='amazon')

    def insert_order(self, order: Dict) -> None:
        self.insert_amazon_order(order)

    def insert_amazon_order(self, order: Dict) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()

        try:
            self._ensure_column('orders', 'track_package_link')
            self._ensure_column('orders', 'asin')
            self._ensure_column('orders', 'unit_price')
            self._ensure_column('orders', 'shipped_quantity')
            
            cursor.execute("PRAGMA table_info(products)")
            product_columns = [row[1] for row in cursor.fetchall()]
            if 'item_url' not in product_columns:
                cursor.execute("ALTER TABLE products ADD COLUMN item_url TEXT")
                self.connection.commit()
            if 'asin' not in product_columns:
                cursor.execute("ALTER TABLE products ADD COLUMN asin TEXT")
                self.connection.commit()
            if 'unit_price' not in product_columns:
                cursor.execute("ALTER TABLE products ADD COLUMN unit_price TEXT")
                self.connection.commit()
            
            cursor.execute("PRAGMA table_info(tracking_numbers)")
            tracking_columns = [row[1] for row in cursor.fetchall()]
            if 'tracking_url' not in tracking_columns:
                cursor.execute("ALTER TABLE tracking_numbers ADD COLUMN tracking_url TEXT")
                self.connection.commit()

            state_value = order.get('state', '')
            website_value = order.get('website', 'Amazon')
            track_package_link = order.get('track_package_link', '')
            asin = order.get('asin', '')
            unit_price = order.get('unit_price', '')
            shipped_quantity = order.get('shipped_quantity', '')
            
            if not asin:
                logger.info(f"Skipping Amazon order {order['number']} - no ASIN, only ASIN versions are stored")
                print(f"Skipping Amazon order {order['number']} - no ASIN, only ASIN versions are stored")
                return
            
            order_id = f"{order['number']}_{asin}"
            
            cursor.execute('SELECT * FROM orders WHERE order_number = ?', (order_id,))
            existing_order = cursor.fetchone()
            
            if existing_order:
                cursor.execute('''
                    UPDATE orders 
                    SET order_date = ?, total_price = ?, status = ?, email_address = ?, 
                        state = ?, website = ?, track_package_link = ?,
                        asin = ?, unit_price = ?, shipped_quantity = ?
                    WHERE order_number = ?
                ''', (order['date'], order['total_price'], order['status'],
                     order['email_address'], state_value, website_value,
                     track_package_link, asin, unit_price,
                     shipped_quantity, order_id))
            else:
                cursor.execute('''
                    INSERT INTO orders (order_number, order_date, total_price, status, email_address, 
                                        state, website, track_package_link,
                                        asin, unit_price, shipped_quantity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (order_id, order['date'], order['total_price'],
                     order['status'], order['email_address'], state_value, website_value,
                     track_package_link, asin, unit_price, shipped_quantity))

            cursor.execute('DELETE FROM products WHERE order_id = ?', (order_id,))
            cursor.execute('DELETE FROM tracking_numbers WHERE order_id = ?', (order_id,))

            for product in order.get('products', []):
                cursor.execute('''
                    INSERT INTO products (order_id, title, price, quantity, item_url, asin, unit_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (order_id, product.get('title', ''), product.get('price', ''), 
                      product.get('quantity', '1'), product.get('item_url', ''),
                      product.get('asin', ''), product.get('unit_price', '')))

            tracking_with_links = order.get('tracking_with_links', [])
            tracking_url_map = {t['tracking_number']: t['tracking_url'] for t in tracking_with_links}
            
            for tracking_number in order.get('tracking', []):
                tracking_url = tracking_url_map.get(tracking_number, '')
                cursor.execute('''
                    INSERT INTO tracking_numbers (order_id, tracking_number, tracking_url)
                    VALUES (?, ?, ?)
                ''', (order_id, tracking_number, tracking_url))

            self.connection.commit()

        except Exception as e:
            logger.error(f"Error inserting Amazon order {order['number']}: {str(e)}")
            print(f"Error inserting Amazon order {order['number']}: {str(e)}")
            self.connection.rollback()

