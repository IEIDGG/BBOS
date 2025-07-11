import re
from bs4 import BeautifulSoup
from typing import Optional, Dict


class XboxParser:
    @staticmethod
    def extract_xbox_code(html_content: str) -> Optional[Dict[str, str]]:
        soup = BeautifulSoup(html_content, 'html.parser')

        code_element = soup.find('strong', string=re.compile(r'Code:'))
        if not code_element:
            return None

        code_match = re.search(r'Code:\s*([A-Z0-9-]+)', code_element.text)
        if not code_match:
            return None
            
        return {
            'code': code_match.group(1),
        }
