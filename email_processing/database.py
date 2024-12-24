"""
Database operations for the Best Buy Order Tracker application.
"""

import sqlite3
import os
from typing import List, Dict, Tuple, Optional
from config.settings import DB_SETTINGS


class DatabaseManager:
    def __init__(self):
        """Initialize database connection and create tables if they don't exist."""
        self.db_file = DB_SETTINGS['filename']
        self.connection = None
        self.create_connection()
        self.create_tables()

    def create_connection(self) -> None:
        """Create a database connection."""
        try:
            self.connection = sqlite3.connect(self.db_file)
        except Exception as e:
            print(f"Error connecting to database: {str(e)}")
            raise

    def create_tables(self) -> None:
        """Create all required database tables."""
        if not self.connection:
            return

        cursor = self.connection.cursor()
        for table_sql in DB_SETTINGS['tables'].values():
            cursor.executescript(table_sql)
        self.connection.commit()

    def insert_order(self, order: Dict) -> None:
        """Insert or update order information."""
        if not self.connection:
            return

        cursor = self.connection.cursor()

        try:
            # Check if order exists
            cursor.execute('SELECT * FROM orders WHERE order_number = ?', (order['number'],))
            existing_order = cursor.fetchone()

            if existing_order:
                # Update existing order
                cursor.execute('''
                    UPDATE orders 
                    SET order_date = ?, total_price = ?, status = ?, email_address = ?
                    WHERE order_number = ?
                ''', (order['date'], order['total_price'], order['status'],
                     order['email_address'], order['number']))
            else:
                # Insert new order
                cursor.execute('''
                    INSERT INTO orders (order_number, order_date, total_price, status, email_address)
                    VALUES (?, ?, ?, ?, ?)
                ''', (order['number'], order['date'], order['total_price'],
                     order['status'], order['email_address']))

            order_id = order['number']

            # Clear existing products and tracking numbers
            cursor.execute('DELETE FROM products WHERE order_id = ?', (order_id,))
            cursor.execute('DELETE FROM tracking_numbers WHERE order_id = ?', (order_id,))

            # Insert products
            for product in order['products']:
                cursor.execute('''
                    INSERT INTO products (order_id, title, price, quantity)
                    VALUES (?, ?, ?, ?)
                ''', (order_id, product['title'], product['price'], product['quantity']))

            # Insert tracking numbers
            for tracking_number in order['tracking']:
                cursor.execute('''
                    INSERT INTO tracking_numbers (order_id, tracking_number)
                    VALUES (?, ?)
                ''', (order_id, tracking_number))

            self.connection.commit()

        except Exception as e:
            print(f"Error inserting order {order['number']}: {str(e)}")
            self.connection.rollback()

    def insert_xbox_code(self, code_data: Dict) -> None:
        """Insert Xbox code information."""
        if not self.connection:
            return

        cursor = self.connection.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO xbox_codes (code, email_date, order_number)
                VALUES (?, ?, ?)
            ''', (code_data['code'], code_data['date'], code_data.get('order_number')))
            self.connection.commit()
        except Exception as e:
            print(f"Error inserting Xbox code: {str(e)}")
            self.connection.rollback()

    def create_successful_orders_view(self) -> None:
        """Create or update the successful orders view."""
        if not self.connection:
            return

        cursor = self.connection.cursor()
        try:
            cursor.execute('DROP TABLE IF EXISTS successful_orders')
            cursor.execute('''
                CREATE TABLE successful_orders AS
                SELECT 
                    o.order_number,
                    o.order_date,
                    o.total_price,
                    o.status,
                    GROUP_CONCAT(p.title, '; ') as title,
                    GROUP_CONCAT(p.quantity, '; ') as quantity,
                    GROUP_CONCAT(t.tracking_number, '; ') as tracking_number
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
            self.connection.commit()
        except Exception as e:
            print(f"Error creating successful orders view: {str(e)}")
            self.connection.rollback()

    def get_order_summary(self) -> Tuple[int, int, int, int]:
        """Get summary statistics for orders."""
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
            print(f"Error getting order summary: {str(e)}")
            return (0, 0, 0, 0)

    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()