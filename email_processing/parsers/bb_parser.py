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
                    kwargs['style'] = lambda v, val=value: v and val in v
                elif attr == 'style_contains_all':
                    kwargs['style'] = lambda v, val=value: v and all(part in v for part in val)
                elif attr == 'href_contains':
                    kwargs['href'] = lambda v, val=value: v and val in v
                else:
                    kwargs[attr] = value
        
        elements = soup.find_all(tag, **kwargs)
        
        if 'text_contains' in config:
            text_filter = config['text_contains']
            elements = [elem for elem in elements if text_filter in elem.text]
        
        if 'text_min_length' in config:
            min_length = config['text_min_length']
            elements = [elem for elem in elements if len(elem.get_text().strip()) >= min_length]
        
        return elements
    
    @classmethod
    def _find_element(cls, soup, selector_config):
        config = selector_config
        tag = config['tag']
        
        kwargs = {}
        if 'attributes' in config:
            for attr, value in config['attributes'].items():
                if attr == 'style_contains':
                    kwargs['style'] = lambda v, val=value: v and val in v
                elif attr == 'style_contains_all':
                    kwargs['style'] = lambda v, val=value: v and all(part in v for part in val)
                elif attr == 'href_contains':
                    kwargs['href'] = lambda v, val=value: v and val in v
                else:
                    kwargs[attr] = value
        
        if 'text_contains' in config or 'text_min_length' in config:
            elements = soup.find_all(tag, **kwargs)
            
            if 'text_contains' in config:
                text_filter = config['text_contains']
                elements = [elem for elem in elements if text_filter in elem.text]
            
            if 'text_min_length' in config:
                min_length = config['text_min_length']
                elements = [elem for elem in elements if len(elem.get_text().strip()) >= min_length]
            
            return elements[0] if elements else None
        
        return soup.find(tag, **kwargs)

    @staticmethod
    def parse_product_details(html_content: str) -> Tuple[List[Dict[str, str]], str]:
        config = OrderParser._load_config()
        soup = BeautifulSoup(html_content, 'lxml')
        products = []
        
        product_config = config['product_parsing']
        
        product_sections = OrderParser._find_elements(soup, product_config['product_sections'])

        for section in product_sections:
            title_tag = OrderParser._find_element(section, product_config['title'])
            if not title_tag:
                continue
            
            title = title_tag.text.strip()
            
            if 'Xbox' in title or 'Game Pass' in title or 'fubo' in title or 'Apple TV' in title or 'Norton' in title:
                continue

            qty_tag = section.find_next('td', string='Qty:')
            qty = qty_tag.find_next_sibling('td').text.strip() if qty_tag else "N/A"

            dollar_spans = section.find_all('span', string=lambda text: text and '$' in text)
            for span in dollar_spans:
                print(f"  - Text: '{span.text}'")
                
            price_tag = section.find(
                product_config['price']['tag'],
                string=lambda text: text and '$' in text,
                style=lambda value: value and product_config['price']['attributes']['style_contains'] in value
            )
            
            if not price_tag and dollar_spans:
                for span in dollar_spans:
                    if '$' in span.text and not span.text.strip() in ['$0.00', '$']:
                        price_tag = span
                        break
                
            price = price_tag.text.strip() if price_tag else "N/A"

            if price != "N/A":
                products.append({
                    'title': title,
                    'quantity': qty,
                    'price': price
                })
                break

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

        if email_type == 'cancellation':
            cancelled_config = order_config['cancelled']
            order_tds = OrderParser._find_elements(soup, cancelled_config['container'])
            for td in order_tds:
                if cancelled_config['container']['text_contains'] in td.text:
                    order_span = td.find(
                        cancelled_config['target']['tag'],
                        style=lambda value: value and all(
                            part in value for part in cancelled_config['target']['attributes']['style_contains_all']
                        )
                    )
                    if order_span:
                        return order_span.text.strip()

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
        print(f"     Format 1 - Found {len(tracking_spans)} potential tracking spans")
        for span in tracking_spans:
            if format1_config['container']['text_contains'] in span.text:
                tracking_link = span.find(format1_config['target']['tag'])
                if tracking_link:
                    tracking_num = tracking_link.text.strip()
                    print(f"     ✓ Format 1 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        format2_config = tracking_config['format_2']
        tracking_tds = OrderParser._find_elements(soup, format2_config['container'])
        print(f"     Format 2 - Found {len(tracking_tds)} potential tracking TDs")
        for td in tracking_tds:
            if format2_config['container']['text_contains'] in td.text:
                print(f"     Format 2 - Text match found in TD")
                tracking_span = td.find(
                    format2_config['target']['tag'],
                    style=lambda value: value and all(
                        part in value for part in format2_config['target']['attributes']['style_contains_all']
                    )
                )
                if tracking_span:
                    tracking_num = tracking_span.text.strip()
                    print(f"     ✓ Format 2 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        format3_config = tracking_config['format_3']
        tracking_tds = OrderParser._find_elements(soup, format3_config['container'])
        print(f"     Format 3 - Found {len(tracking_tds)} potential tracking TDs")
        for td in tracking_tds:
            if format3_config['container']['text_contains'] in td.text:
                print(f"     Format 3 - Text match found in TD")
                tracking_span = td.find(
                    format3_config['target']['tag'],
                    style=lambda value: value and all(
                        part in value for part in format3_config['target']['attributes']['style_contains_all']
                    )
                )
                if tracking_span:
                    tracking_num = tracking_span.text.strip()
                    print(f"     ✓ Format 3 - Extracted: {tracking_num}")
                    tracking_numbers.append(tracking_num)

        if not tracking_numbers:
            all_tds_with_tracking = soup.find_all('td', string=lambda text: text and 'tracking' in text.lower())
            if all_tds_with_tracking:
                print(f"     ⚠ Found {len(all_tds_with_tracking)} TDs containing 'tracking' but couldn't extract numbers")
                for td in all_tds_with_tracking[:3]:
                    print(f"       Sample: {td.text.strip()[:100]}")

        return tracking_numbers

    @staticmethod
    def extract_shipping_address(soup: BeautifulSoup) -> str:
        shipping_tds = soup.find_all('td')
        old_format_tds = [td for td in shipping_tds if 'Your order is shipping to:' in td.get_text()]
        
        for td in old_format_tds:
            spans = td.find_all('span')
            
            for span in spans:
                span_text = span.get_text().strip()
                span_style = span.get('style', '')
                
                is_address = (
                    len(span_text.split()) > 3 and 
                    (',' in span_text or '<br>' in str(span)) and
                    any(char.isdigit() for char in span_text) and
                    not span_text.lower().startswith(('status', 'ready', 'product', 'shipped', 'delivered'))
                )
                
                has_style = (
                    'font-size: 20px' in span_style and 'font-weight: 700' in span_style
                ) or (
                    'font-weight: 700' in span_style and 'font-size' in span_style
                )
                
                if is_address and has_style:
                    address_text = span.get_text().replace('<br>', '\n').replace('<br/>', '\n')
                    lines = [line.strip() for line in address_text.split('\n') if line.strip()]
                    
                    last_line = lines[-1] if lines else ''
                    if ', ' in last_line:
                        parts = last_line.split(', ')
                        if len(parts) >= 2:
                            state_zip = parts[1].strip()
                            if state_zip:
                                return state_zip
        
        new_format_tds = [td for td in shipping_tds if 'Shipping to:' in td.get_text() and 'Your order is shipping to:' not in td.get_text()]
        
        for td in new_format_tds:
            parent = td.find_parent('tr')
            if parent:
                next_row = parent.find_next_sibling('tr')
                if next_row:
                    address_span = next_row.find('span', style=lambda v: v and 'font-size: 16px' in v)
                    if address_span:
                        address_text = address_span.get_text().strip()
                        if ', ' in address_text and any(char.isdigit() for char in address_text):
                            parts = address_text.split(', ')
                            if len(parts) >= 2:
                                state_zip = parts[1].strip()
                                if state_zip:
                                    return state_zip
        
        return ''