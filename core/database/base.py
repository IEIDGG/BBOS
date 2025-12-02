import sqlite3
import logging
from typing import List, Dict, Tuple, Optional, Set
from datetime import datetime
from core.utils import get_db_filename

logger = logging.getLogger(__name__)


class BaseDatabaseManager:
    def __init__(self, db_config: Dict, email: str = None, service: str = 'bestbuy'):
        self.db_config = db_config
        self.service = service
        if email:
            self.db_file = get_db_filename(email, service)
        else:
            self.db_file = db_config.get('filename', get_db_filename(None, service))
        self.connection = None
        self.create_connection()
        self.create_tables()

    def create_connection(self) -> None:
        try:
            logger.info(f"Connecting to database: {self.db_file}")
            print(f"Connecting to database: {self.db_file}")
            self.connection = sqlite3.connect(self.db_file)
        except Exception as e:
            logger.error(f"Error connecting to database: {str(e)}")
            print(f"Error connecting to database: {str(e)}")
            raise

    def create_tables(self) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()
        for table_sql in self.db_config['tables'].values():
            cursor.executescript(table_sql)
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, col_type: str = 'TEXT') -> None:
        if not self.connection:
            return
        cursor = self.connection.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            self.connection.commit()

    def get_all_orders(self) -> List[Dict]:
        if not self.connection:
            return []

        cursor = self.connection.cursor()
        try:
            cursor.execute('SELECT order_number, order_date, total_price, status, email_address, state FROM orders')
            rows = cursor.fetchall()
            
            orders = []
            for row in rows:
                orders.append({
                    'number': row[0],
                    'order_number': row[0],
                    'date': row[1],
                    'total_price': row[2],
                    'status': row[3],
                    'email_address': row[4],
                    'state': row[5] if len(row) > 5 else ''
                })
            return orders
        except Exception as e:
            logger.error(f"Error getting all orders: {str(e)}")
            print(f"Error getting all orders: {str(e)}")
            return []

    def get_order_summary(self) -> Tuple[int, int, int, int]:
        if not self.connection:
            return (0, 0, 0, 0)

        cursor = self.connection.cursor()
        try:
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT order_number) as unique_orders,
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status = 'Shipped' THEN 1 ELSE 0 END) as shipped_count,
                    (SELECT COUNT(*) FROM tracking_numbers) as tracking_numbers_count
                FROM orders
            ''')
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting order summary: {str(e)}")
            print(f"Error getting order summary: {str(e)}")
            return (0, 0, 0, 0)

    def get_order_by_number(self, order_number: str) -> Optional[Dict]:
        if not self.connection:
            return None

        cursor = self.connection.cursor()
        try:
            cursor.execute('''
                SELECT order_number, order_date, total_price, status, email_address, state
                FROM orders
                WHERE order_number = ?
            ''', (order_number,))
            order_row = cursor.fetchone()
            
            if not order_row:
                return None
            
            cursor.execute('''
                SELECT title, price, quantity
                FROM products
                WHERE order_id = ?
            ''', (order_number,))
            products = []
            for product_row in cursor.fetchall():
                products.append({
                    'title': product_row[0],
                    'price': product_row[1],
                    'quantity': product_row[2]
                })
            
            cursor.execute("PRAGMA table_info(tracking_numbers)")
            tracking_columns = [row[1] for row in cursor.fetchall()]
            has_tracking_url = 'tracking_url' in tracking_columns
            
            if has_tracking_url:
                cursor.execute('''
                    SELECT tracking_number, tracking_url
                    FROM tracking_numbers
                    WHERE order_id = ?
                ''', (order_number,))
                tracking_numbers = []
                tracking_with_links = []
                for row in cursor.fetchall():
                    tracking_numbers.append(row[0])
                    if row[1]:
                        tracking_with_links.append({
                            'tracking_number': row[0],
                            'tracking_url': row[1]
                        })
            else:
                cursor.execute('''
                    SELECT tracking_number
                    FROM tracking_numbers
                    WHERE order_id = ?
                ''', (order_number,))
                tracking_numbers = [row[0] for row in cursor.fetchall()]
                tracking_with_links = []
            
            return {
                'number': order_row[0],
                'order_number': order_row[0],
                'date': order_row[1],
                'total_price': order_row[2],
                'status': order_row[3],
                'email_address': order_row[4],
                'state': order_row[5] if len(order_row) > 5 else '',
                'products': products,
                'tracking': tracking_numbers,
                'tracking_with_links': tracking_with_links
            }
        except Exception as e:
            logger.error(f"Error getting order by number: {str(e)}")
            print(f"Error getting order by number: {str(e)}")
            return None

    def get_latest_orders(self, limit: int = 1, with_tracking_only: bool = True) -> List[Dict]:
        if not self.connection:
            return []

        cursor = self.connection.cursor()
        try:
            if with_tracking_only:
                cursor.execute('''
                    SELECT DISTINCT o.order_number
                    FROM orders o
                    INNER JOIN tracking_numbers t ON o.order_number = t.order_id
                    WHERE o.status != 'Cancelled'
                    ORDER BY o.order_date DESC, o.order_number DESC
                    LIMIT ?
                ''', (limit,))
            else:
                cursor.execute('''
                    SELECT order_number
                    FROM orders
                    WHERE status != 'Cancelled'
                    ORDER BY order_date DESC, order_number DESC
                    LIMIT ?
                ''', (limit,))
            
            order_numbers = [row[0] for row in cursor.fetchall()]
            
            orders = []
            for order_number in order_numbers:
                order = self.get_order_by_number(order_number)
                if order:
                    orders.append(order)
            
            return orders
        except Exception as e:
            logger.error(f"Error getting latest orders: {str(e)}")
            print(f"Error getting latest orders: {str(e)}")
            return []

    def get_orders_with_tracking_since_date(self, start_date: str, end_date: Optional[str] = None) -> List[Dict]:
        if not self.connection:
            return []

        cursor = self.connection.cursor()
        try:
            if end_date is None:
                end_date = start_date
            cursor.execute('''
                SELECT DISTINCT o.order_number
                FROM orders o
                INNER JOIN tracking_numbers t ON o.order_number = t.order_id
                WHERE o.status != 'Cancelled'
                AND DATE(o.order_date) BETWEEN DATE(?) AND DATE(?)
                ORDER BY o.order_date DESC, o.order_number DESC
            ''', (start_date, end_date))
            
            order_numbers = [row[0] for row in cursor.fetchall()]
            
            orders = []
            for order_number in order_numbers:
                order = self.get_order_by_number(order_number)
                if order and order.get('tracking'):
                    orders.append(order)
            
            return orders
        except Exception as e:
            logger.error(f"Error getting orders with tracking since date: {str(e)}")
            print(f"Error getting orders with tracking since date: {str(e)}")
            return []

    def update_order_address(self, order_number: str, state_code: str) -> None:
        if not self.connection:
            logger.error(f"No database connection for updating address of order {order_number}")
            print(f"ERROR: No database connection for updating address of order {order_number}")
            return

        cursor = self.connection.cursor()
        try:
            self._ensure_column('orders', 'state')
            
            cursor.execute('''
                UPDATE orders 
                SET state = ?
                WHERE order_number = ?
            ''', (state_code, order_number))
            
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"Error updating order state for {order_number}: {str(e)}")
            print(f"Error updating order state for {order_number}: {str(e)}")
            self.connection.rollback()

    def _ensure_submitted_tracking_keys_table(self) -> None:
        if not self.connection:
            return
        
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='submitted_tracking_keys'")
            if not cursor.fetchone():
                table_sql = self.db_config['tables'].get('submitted_tracking_keys')
                if table_sql:
                    cursor.executescript(table_sql)
                    self.connection.commit()
        except Exception as e:
            logger.error(f"Error ensuring submitted_tracking_keys table exists: {str(e)}")
            print(f"Error ensuring submitted_tracking_keys table exists: {str(e)}")

    def get_submitted_tracking_keys(self) -> Set[str]:
        if not self.connection:
            return set()

        self._ensure_submitted_tracking_keys_table()
        cursor = self.connection.cursor()
        try:
            cursor.execute('SELECT tracking_key FROM submitted_tracking_keys')
            keys = {row[0] for row in cursor.fetchall()}
            return keys
        except Exception as e:
            logger.error(f"Error getting submitted tracking keys: {str(e)}")
            print(f"Error getting submitted tracking keys: {str(e)}")
            return set()

    def add_submitted_tracking_key(self, order_number: str, tracking_number: str, tracking_key: str) -> None:
        if not self.connection:
            return

        self._ensure_submitted_tracking_keys_table()
        cursor = self.connection.cursor()
        try:
            submitted_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                INSERT OR IGNORE INTO submitted_tracking_keys 
                (tracking_key, order_number, tracking_number, submitted_date)
                VALUES (?, ?, ?, ?)
            ''', (tracking_key, order_number, tracking_number, submitted_date))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error adding submitted tracking key: {str(e)}")
            print(f"Error adding submitted tracking key: {str(e)}")
            self.connection.rollback()

    def add_submitted_tracking_keys_batch(self, keys_data: List[Dict[str, str]]) -> None:
        if not self.connection:
            return

        self._ensure_submitted_tracking_keys_table()
        cursor = self.connection.cursor()
        try:
            submitted_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for key_data in keys_data:
                cursor.execute('''
                    INSERT OR IGNORE INTO submitted_tracking_keys 
                    (tracking_key, order_number, tracking_number, submitted_date)
                    VALUES (?, ?, ?, ?)
                ''', (key_data['tracking_key'], key_data['order_number'], 
                      key_data['tracking_number'], submitted_date))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error adding submitted tracking keys batch: {str(e)}")
            print(f"Error adding submitted tracking keys batch: {str(e)}")
            self.connection.rollback()

    def is_tracking_key_submitted(self, tracking_key: str) -> bool:
        if not self.connection:
            return False

        self._ensure_submitted_tracking_keys_table()
        cursor = self.connection.cursor()
        try:
            cursor.execute('SELECT 1 FROM submitted_tracking_keys WHERE tracking_key = ? LIMIT 1', (tracking_key,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking submitted tracking key: {str(e)}")
            print(f"Error checking submitted tracking key: {str(e)}")
            return False

    def create_successful_orders_view(self) -> None:
        if not self.connection:
            return

        cursor = self.connection.cursor()
        try:
            cursor.execute("PRAGMA table_info(orders)")
            columns = [row[1] for row in cursor.fetchall()]
            has_website = 'website' in columns
            has_asin = 'asin' in columns
            has_unit_price = 'unit_price' in columns
            has_shipped_qty = 'shipped_quantity' in columns
            
            cursor.execute("PRAGMA table_info(tracking_numbers)")
            tracking_columns = [row[1] for row in cursor.fetchall()]
            has_tracking_url = 'tracking_url' in tracking_columns
            
            if has_tracking_url:
                tracking_select = '''
                    GROUP_CONCAT(
                        CASE 
                            WHEN t.tracking_url IS NOT NULL AND t.tracking_url != '' 
                            THEN t.tracking_url
                            ELSE t.tracking_number 
                        END, '; '
                    ) as tracking_number
                '''
            else:
                tracking_select = "GROUP_CONCAT(t.tracking_number, '; ') as tracking_number"
            
            asin_col = "COALESCE(o.asin, '') as asin," if has_asin else ""
            unit_price_col = "COALESCE(o.unit_price, '') as unit_price," if has_unit_price else ""
            shipped_qty_col = "COALESCE(o.shipped_quantity, '') as shipped_quantity," if has_shipped_qty else ""
            
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS successful_orders_temp AS
                SELECT 
                    COALESCE(o.website, 'BestBuy') as website,
                    o.order_number,
                    {asin_col}
                    o.order_date,
                    o.total_price,
                    {unit_price_col}
                    {shipped_qty_col}
                    o.status,
                    GROUP_CONCAT(p.title, '; ') as title,
                    GROUP_CONCAT(p.quantity, '; ') as quantity,
                    {tracking_select},
                    COALESCE(o.state, '') as state,
                    COALESCE(o.email_address, '') as email_address
                FROM 
                    orders o
                LEFT JOIN 
                    products p ON o.order_number = p.order_id
                LEFT JOIN 
                    tracking_numbers t ON o.order_number = t.order_id
                WHERE 
                    o.status != 'Cancelled'
                GROUP BY 
                    o.order_number
            ''')
            
            cursor.execute('DROP TABLE IF EXISTS successful_orders')
            cursor.execute('ALTER TABLE successful_orders_temp RENAME TO successful_orders')
            
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error creating successful orders view: {str(e)}")
            print(f"Error creating successful orders view: {str(e)}")
            self.connection.rollback()

    def close(self) -> None:
        if self.connection:
            self.connection.close()

