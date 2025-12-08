"""Email processing package for Best Buy Order Tracker."""

from .connector import EmailConnector
from .handlers import (
    OrderEmailHandler,
    XboxEmailHandler,
    CostcoEmailHandler,
    AmazonEmailHandler
)
from .processor import EmailProcessor

__all__ = [
    'EmailConnector',
    'OrderEmailHandler',
    'XboxEmailHandler',
    'CostcoEmailHandler',
    'AmazonEmailHandler',
    'EmailProcessor'
]
