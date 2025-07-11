import json
import os
from bs4 import BeautifulSoup
from typing import Tuple, List, Dict, Any


class OrderParser:
    _config = None
    
    @classmethod
    def _load_config(cls):
        if cls._config is None:
            config_path = os.path.join(os.path.dirname(__file__), 'html_selectors.json')
            with open(config_path, 'r') as f:
                cls._config = json.load(f)
        return cls._config
    
    @classmethod
    def _find_elements(cls, soup, selector_config):
        config = selector_config
        tag = config['tag']
        
        kwargs = {}
        if 'attributes' in config:
            for attr, value in config['attributes'].items():
                if attr == 'style_contains':
                    kwargs['style'] = lambda v: v and value in v
                elif attr == 'style_contains_all':
                    kwargs['style'] = lambda v: v and all(part in v for part in value)
                else:
                    kwargs[attr] = value
        
        elements = soup.find_all(tag, **kwargs)
        
        if 'text_contains' in config:
            text_filter = config['text_contains']
            elements = [elem for elem in elements if text_filter in elem.text]
        
        return elements
    
    @classmethod
    def _find_element(cls, soup, selector_config):
        config = selector_config
        tag = config['tag']
        
        kwargs = {}
        if 'attributes' in config:
            for attr, value in config['attributes'].items():
                if attr == 'style_contains':
                    kwargs['style'] = lambda v: v and value in v
                elif attr == 'style_contains_all':
                    kwargs['style'] = lambda v: v and all(part in v for part in value)
                else:
                    kwargs[attr] = value
        
        if 'text_contains' in config:
            text_filter = config['text_contains']
            elements = soup.find_all(tag, **kwargs)
            for elem in elements:
                if text_filter in elem.text:
                    return elem
            return None
        
        return soup.find(tag, **kwargs)

    @staticmethod
    def parse_product_details(html_content: str) -> Tuple[List[Dict[str, str]], str]:
        config = OrderParser._load_config()
        soup = BeautifulSoup(html_content, 'html.parser')
        products = []
        
        product_config = config['product_parsing']
        
        product_sections = OrderParser._find_elements(soup, product_config['product_sections'])

        for section in product_sections:
            title_tag = section.find(
                product_config['title']['tag'],
                **{k: v for k, v in product_config['title']['attributes'].items()}
            )
            if not title_tag:
                continue

            qty_tag = section.find_next('td', string='Qty:')
            qty = qty_tag.find_next_sibling('td').text.strip() if qty_tag else "N/A"

            price_tag = section.find(
                product_config['price']['tag'],
                string=lambda text: text and '$' in text,
                style=lambda value: value and product_config['price']['attributes']['style_contains'] in value
            )
            price = price_tag.text.strip() if price_tag else "N/A"

            if price != "N/A":
                products.append({
                    'title': title_tag.text.strip(),
                    'quantity': qty,
                    'price': price
                })

        total_td = OrderParser._find_element(soup, product_config['total'])
        total_price = total_td.text.strip() if total_td else "N/A"

        return products, total_price

    @staticmethod
    def extract_order_number(soup: BeautifulSoup, email_type: str) -> str:
        config = OrderParser._load_config()
        order_config = config['order_number']
        
        if email_type == 'confirmation':
            order_span = OrderParser._find_element(soup, order_config['confirmation'])
            return order_span.text.strip() if order_span else None

        order_span = OrderParser._find_element(soup, order_config['shipped_cancelled'])
        if order_span:
            text = order_span.text.strip()
            replace_config = order_config['shipped_cancelled']['text_replace']
            return text.replace(replace_config['from'], replace_config['to'])

        alt_config = order_config['alternative']
        order_tds = OrderParser._find_elements(soup, alt_config['container'])
        for td in order_tds:
            if alt_config['container']['text_contains'] in td.text:
                order_span = td.find(
                    alt_config['target']['tag'],
                    style=lambda value: value and all(
                        part in value for part in alt_config['target']['attributes']['style_contains_all']
                    )
                )
                if order_span:
                    return order_span.text.strip()

        return None

    @staticmethod
    def extract_tracking_numbers(soup: BeautifulSoup) -> List[str]:
        config = OrderParser._load_config()
        tracking_config = config['tracking_numbers']
        tracking_numbers = []

        format1_config = tracking_config['format_1']
        tracking_spans = soup.find_all(
            format1_config['container']['tag'],
            **format1_config['container']['attributes']
        )
        for span in tracking_spans:
            if format1_config['container']['text_contains'] in span.text:
                tracking_link = span.find(format1_config['target']['tag'])
                if tracking_link:
                    tracking_numbers.append(tracking_link.text.strip())

        format2_config = tracking_config['format_2']
        tracking_tds = OrderParser._find_elements(soup, format2_config['container'])
        for td in tracking_tds:
            if format2_config['container']['text_contains'] in td.text:
                tracking_span = td.find(
                    format2_config['target']['tag'],
                    style=lambda value: value and all(
                        part in value for part in format2_config['target']['attributes']['style_contains_all']
                    )
                )
                if tracking_span:
                    tracking_numbers.append(tracking_span.text.strip())

        return tracking_numbers