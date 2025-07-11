"""Email processing package for Best Buy Order Tracker."""

from .connector import EmailConnector
from .handlers import OrderEmailHandler, XboxEmailHandler
from .processor import EmailProcessor