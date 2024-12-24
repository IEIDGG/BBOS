"""
Parser for Xbox Game Pass code emails from Best Buy.
"""

import re
from bs4 import BeautifulSoup
from typing import Optional, Dict


class XboxParser:
    @staticmethod
    def extract_xbox_code(html_content: str) -> Optional[Dict[str, str]]:
        """
        Extract Xbox Game Pass code from email HTML content.

        Returns:
            Dictionary containing the code and associated order number if found,
            None otherwise
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find the code section
        code_element = soup.find('strong', string=re.compile(r'Code:'))
        if not code_element:
            return None

        # Extract the code using regex
        code_match = re.search(r'Code:\s*([A-Z0-9-]+)', code_element.text)
        if not code_match:
            return None

        # Try to find associated order number
        order_number = None
        order_text = soup.find(string=re.compile(r'Order\s*#'))
        if order_text:
            order_match = re.search(r'Order\s*#\s*(BBY01-\d+)', order_text)
            if order_match:
                order_number = order_match.group(1)

        return {
            'code': code_match.group(1),
            'order_number': order_number
        }