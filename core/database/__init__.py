from typing import Optional
from .base import BaseDatabaseManager
from .bestbuy import BestBuyDatabaseManager
from .amazon import AmazonDatabaseManager
from .costco import CostcoDatabaseManager


def DatabaseManager(db_config=None, email: str = None, service: str = 'bestbuy'):
    service_lower = service.lower() if service else 'bestbuy'
    
    if service_lower == 'amazon':
        return AmazonDatabaseManager(email=email)
    elif service_lower == 'costco':
        return CostcoDatabaseManager(email=email)
    else:
        return BestBuyDatabaseManager(email=email)


__all__ = [
    'DatabaseManager',
    'BaseDatabaseManager',
    'BestBuyDatabaseManager',
    'AmazonDatabaseManager',
    'CostcoDatabaseManager'
]

