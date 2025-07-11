import json
import os
import re
from bs4 import BeautifulSoup
from typing import Optional, Dict


class XboxParser:
    _config = None
    
    @classmethod
    def _load_config(cls):
        if cls._config is None:
            config_path = os.path.join(os.path.dirname(__file__), 'html_selectors.json')
            with open(config_path, 'r') as f:
                cls._config = json.load(f)
        return cls._config

    @staticmethod
    def extract_xbox_code(html_content: str) -> Optional[Dict[str, str]]:
        config = XboxParser._load_config()
        xbox_config = config['xbox_parsing']
        soup = BeautifulSoup(html_content, 'html.parser')

        code_element = soup.find(
            xbox_config['code_extraction']['element']['tag'],
            string=re.compile(xbox_config['code_extraction']['element']['text_regex'])
        )
        if not code_element:
            return None

        code_match = re.search(
            xbox_config['code_extraction']['code_regex'],
            code_element.text
        )
        if not code_match:
            return None

        return {
            'code': code_match.group(1),
        }