import re
import json
import os
from bs4 import BeautifulSoup
from typing import Optional, Dict


class XboxParser:
    def __init__(self):
        config_path = os.path.join(os.path.dirname(__file__), 'html_selectors.json')
        with open(config_path, 'r') as f:
            self.selectors = json.load(f)['xbox_parsing']
    
    def _find_element_by_selector(self, soup: BeautifulSoup, selector_config: dict):
        tag = selector_config.get('tag')
        attributes = selector_config.get('attributes', {})
        text_contains = selector_config.get('text_contains')
        
        elements = soup.find_all(tag)
        
        for element in elements:
            if text_contains and text_contains not in element.get_text():
                continue
                
            style = element.get('style', '')
            if 'style_contains_all' in attributes:
                if not all(attr in style for attr in attributes['style_contains_all']):
                    continue
            elif 'style_contains' in attributes:
                if attributes['style_contains'] not in style:
                    continue
                    
            return element
        
        return None
    
    def extract_xbox_code(self, html_content: str) -> Optional[Dict[str, str]]:
        soup = BeautifulSoup(html_content, 'lxml')
        
        title_element = self._find_element_by_selector(soup, self.selectors['title'])
        title = title_element.get_text().strip() if title_element else None
        print(title)
        
        code_container = self._find_element_by_selector(soup, self.selectors['code_extraction']['container'])
        if not code_container:
            return None
            
        code_element = code_container.find_next_sibling('strong')
        if not code_element:
            return None
            
        code = code_element.get_text().strip()
        
        print(code)

        if code[-1] != 'Z':
            return None

        result = {'code': code}
        if title:
            result['title'] = title
            
        return result