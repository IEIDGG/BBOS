import os
import sqlite3
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from core.utils import get_email_username, clean_filename

logger = logging.getLogger(__name__)

app = FastAPI(title="BBOS Orders API", version="1.0.0")


def find_database_file(identifier: str) -> Optional[str]:
    db_dir = 'db'
    if not os.path.exists(db_dir):
        logger.error(f"Database directory not found: {db_dir}")
        return None
    
    if '@' in identifier:
        username = get_email_username(identifier)
    else:
        username = clean_filename(identifier)
    
    db_path = os.path.join(db_dir, f'{username}.sqlite3')
    
    if os.path.exists(db_path):
        return db_path
    
    logger.warning(f"Database file not found: {db_path}")
    return None


def get_successful_orders(db_path: str) -> List[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='successful_orders'")
        if not cursor.fetchone():
            logger.warning(f"successful_orders table not found in {db_path}")
            conn.close()
            return []
        
        cursor.execute("PRAGMA table_info(successful_orders)")
        columns = [row[1] for row in cursor.fetchall()]
        
        query = f"SELECT * FROM successful_orders ORDER BY order_date DESC"
        cursor.execute(query)
        
        rows = cursor.fetchall()
        orders = []
        
        for row in rows:
            order_dict = {}
            for idx, col_name in enumerate(columns):
                value = row[idx]
                order_dict[col_name] = value if value is not None else ""
            orders.append(order_dict)
        
        conn.close()
        return orders
    
    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
        raise Exception(f"Database error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise


@app.get("/orders/successful")
async def get_successful_orders_endpoint(
    email: Optional[str] = Query(None, description="Email address of the account"),
    username: Optional[str] = Query(None, description="Username of the account")
):
    if not email and not username:
        raise HTTPException(
            status_code=400,
            detail="Either 'email' or 'username' parameter is required"
        )
    
    if email and username:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'email' or 'username', not both"
        )
    
    identifier = email if email else username
    logger.info(f"Fetching successful orders for: {identifier}")
    
    db_path = find_database_file(identifier)
    
    if not db_path:
        raise HTTPException(
            status_code=404,
            detail=f"Database not found for account: {identifier}"
        )
    
    try:
        orders = get_successful_orders(db_path)
        logger.info(f"Found {len(orders)} successful orders for {identifier}")
        
        return JSONResponse(content={
            "success": True,
            "account": identifier,
            "database": db_path,
            "count": len(orders),
            "orders": orders
        })
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "BBOS Orders API"}
