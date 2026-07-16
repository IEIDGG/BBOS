import json
import os
import re
import logging
from bs4 import BeautifulSoup
from typing import Tuple, List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class CostcoParser:
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
                elif attr == 'class':
                    kwargs['class_'] = value
                elif attr == 'id':
                    kwargs['id'] = value
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
                elif attr == 'class':
                    kwargs['class_'] = value
                elif attr == 'id':
                    kwargs['id'] = value
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
    def _clean_text(text: str) -> str:
        if not text:
            return text
        text = text.replace('\u200c', '')
        text = text.replace('&zwnj;', '')
        text = text.replace('\u200b', '')
        text = text.replace('\xad', '')
        text = text.replace('\xa0', ' ')
        text = text.replace('&nbsp;', ' ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _normalize_price(price: str) -> str:
        if not price:
            return price
        price = price.replace(' ', '')
        if not price.startswith('$'):
            price = '$' + price
        return price

    @staticmethod
    def _is_valid_costco_order_number(text: str) -> bool:
        if not text or not text.isdigit():
            return False
        if len(text) != 10:
            return False
        if not text.startswith('12'):
            return False
        if text.startswith('1Z'):
            return False
        return True

    @staticmethod
    def extract_order_number_from_subject(subject: str, email_type: str) -> Optional[str]:
        if not subject:
            return None
        
        if email_type == 'cancellation':
            patterns = [r'Order\s*#(\d{10})']
        elif email_type == 'shipped':
            patterns = [
                r'Order\s*Number\s*(\d{10})',
                r'order\s+(\d{10})\s+has\s+shipped',
            ]
        else:
            patterns = [r'Order\s*Number\s*(\d{10})']
        
        for pattern in patterns:
            match = re.search(pattern, subject, re.IGNORECASE)
            if match:
                order_num = match.group(1)
                if CostcoParser._is_valid_costco_order_number(order_num):
                    logger.debug(f"Extracted order number from subject: {order_num}")
                    return order_num
        return None

    @staticmethod
    def extract_order_number(soup: BeautifulSoup, email_type: str, subject: str = None) -> Optional[str]:
        if subject:
            order_num = CostcoParser.extract_order_number_from_subject(subject, email_type)
            if order_num:
                return order_num
        
        config = CostcoParser._load_config()
        costco_config = config.get('costco_parsing', {})
        order_config = costco_config.get('order_number', {})
        
        if email_type == 'confirmation':
            selector = order_config.get('confirmation', {})
            order_link = CostcoParser._find_element(soup, selector)
            if order_link:
                order_num = CostcoParser._clean_text(order_link.text)
                if CostcoParser._is_valid_costco_order_number(order_num):
                    logger.debug(f"Extracted order number from HTML: {order_num}")
                    return order_num
        
        elif email_type == 'cancellation':
            selector = order_config.get('cancellation', {})
            order_link = CostcoParser._find_element(soup, selector)
            if order_link:
                order_num = CostcoParser._clean_text(order_link.text)
                if CostcoParser._is_valid_costco_order_number(order_num):
                    logger.debug(f"Extracted cancellation order number from HTML: {order_num}")
                    return order_num
        
        elif email_type == 'shipped':
            selector = order_config.get('shipped', {})
            order_link = CostcoParser._find_element(soup, selector)
            if order_link:
                order_num = CostcoParser._clean_text(order_link.text)
                if CostcoParser._is_valid_costco_order_number(order_num):
                    logger.debug(f"Extracted shipped order number from HTML: {order_num}")
                    return order_num
            
            tracking_links = soup.find_all('a', href=lambda h: h and 'shipmenttracking.costco.com' in h.lower())
            for link in tracking_links:
                href = link.get('href', '')
                match = re.search(r'/odn/(\d{10})', href)
                if match:
                    order_num = match.group(1)
                    if CostcoParser._is_valid_costco_order_number(order_num):
                        logger.debug(f"Extracted shipped order number from tracking URL: {order_num}")
                        return order_num
        
        order_links = soup.find_all('a', href=lambda h: h and 'costco.com' in h.lower())
        for link in order_links:
            text = CostcoParser._clean_text(link.text)
            if CostcoParser._is_valid_costco_order_number(text):
                logger.debug(f"Extracted order number from link: {text}")
                return text
        
        return None

    @staticmethod
    def extract_order_date(soup: BeautifulSoup) -> Optional[str]:
        tds = soup.find_all('td', class_='order-placed-text')
        for td in tds:
            if 'Order Placed' in td.get_text():
                parent_tr = td.find_parent('tr')
                if parent_tr:
                    sibling_tds = parent_tr.find_all('td')
                    for sibling in sibling_tds:
                        text = CostcoParser._clean_text(sibling.get_text())
                        if text and 'Order Placed' not in text:
                            date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', text)
                            if date_match:
                                logger.debug(f"Extracted order date: {date_match.group()}")
                                return date_match.group()
        
        all_tds = soup.find_all('td')
        for td in all_tds:
            text = td.get_text()
            if 'Order Placed' in text and 'Order Number' not in text:
                date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', text)
                if date_match:
                    logger.debug(f"Extracted order date from text: {date_match.group()}")
                    return date_match.group()
        
        page_text = soup.get_text()
        date_match = re.search(r'Order Placed\s*[:\s]*\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', page_text)
        if date_match:
            full_match = date_match.group()
            date_part = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', full_match)
            if date_part:
                logger.debug(f"Extracted order date from page text: {date_part.group()}")
                return date_part.group()
        
        return None

    @staticmethod
    def extract_cancellation_date(soup: BeautifulSoup) -> Optional[str]:
        config = CostcoParser._load_config()
        costco_config = config.get('costco_parsing', {})
        
        tds = soup.find_all('td')
        for td in tds:
            if 'Cancellation Date' in td.get_text():
                next_td = td.find_next('td')
                if next_td:
                    date_text = CostcoParser._clean_text(next_td.get_text())
                    if date_text:
                        logger.debug(f"Extracted cancellation date: {date_text}")
                        return date_text
        
        return None

    @staticmethod
    def extract_membership_number(soup: BeautifulSoup) -> Optional[str]:
        page_text = soup.get_text()
        match = re.search(r'\d{11,12}', page_text)
        if match:
            membership = match.group(0)
            if membership.startswith('111') and len(membership) == 12:
                logger.debug(f"Extracted membership number via regex: {membership}")
                return membership
        
        logger.debug("No membership number found")
        return "N/A"

    @staticmethod
    def extract_shipping_address(soup: BeautifulSoup) -> Dict[str, str]:
        address = {
            'name': '',
            'address1': '',
            'address2': '',
            'city': '',
            'state': '',
            'zip': ''
        }
        
        shipping_table = soup.find('table', id='shipping-address-table')
        if shipping_table:
            spans = shipping_table.find_all('span')
            address_parts = []
            for span in spans:
                text = CostcoParser._clean_text(span.get_text())
                if text and 'Shipping Address' not in text:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    address_parts.extend(lines)
            
            if address_parts:
                CostcoParser._populate_address_from_parts(address, address_parts)
                logger.debug(f"Extracted shipping address: {address}")
                return address
        
        for h3 in soup.find_all('h3'):
            if 'Shipping Address' not in CostcoParser._clean_text(h3.get_text()):
                continue
            address_p = h3.find_next_sibling('p')
            if not address_p:
                parent = h3.parent
                if parent:
                    address_p = parent.find('p')
            if not address_p:
                continue
            raw_text = address_p.get_text(separator='\n')
            address_parts = [CostcoParser._clean_text(line) for line in raw_text.split('\n')]
            address_parts = [line for line in address_parts if line]
            if address_parts:
                CostcoParser._populate_address_from_parts(address, address_parts)
                logger.debug(f"Extracted shipping address from new template: {address}")
                return address
        
        return address

    @staticmethod
    def _populate_address_from_parts(address: Dict[str, str], address_parts: List[str]) -> None:
        if len(address_parts) >= 1:
            address['name'] = address_parts[0]
        if len(address_parts) >= 2:
            address['address1'] = address_parts[1]
        if len(address_parts) >= 4:
            address['address2'] = address_parts[2]
            city_state_zip = address_parts[3]
        else:
            city_state_zip = address_parts[-1] if len(address_parts) > 2 else ''
        
        if city_state_zip:
            match = re.match(r'(.+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)', city_state_zip)
            if match:
                address['city'] = match.group(1).strip()
                address['state'] = match.group(2)
                address['zip'] = match.group(3)

    @staticmethod
    def _is_valid_membership_number(text: str) -> bool:
        if not text or not text.isdigit():
            return False
        if len(text) == 12 and text.startswith('111'):
            return True
        return False

    @staticmethod
    def _is_valid_tracking(text: str) -> bool:
        if not text or len(text) < 10:
            return False
        text = text.upper().strip()
        if len(text) == 10 and text.isdigit() and text.startswith('12'):
            return False
        if CostcoParser._is_valid_membership_number(text):
            return False
        if re.match(r'^1Z[A-Z0-9]{16}$', text):
            return True
        if re.match(r'^\d{11,22}$', text):
            if len(text) == 12 and text.startswith('111'):
                return False
            return True
        if re.match(r'^[A-Z]{2}\d{9}US$', text):
            return True
        if re.match(r'^94\d{20,22}$', text):
            return True
        if re.match(r'^[A-Z0-9]{12,22}$', text) and not text.isdigit():
            return True
        return False

    @staticmethod
    def extract_tracking_numbers(soup: BeautifulSoup, html_content: str = None) -> List[str]:
        tracking_numbers = []
        
        carrier_line_pattern = re.compile(
            r'(?:United Parcel Service|UPS|USPS|United States Postal(?:\s+Service)?|FedEx|OnTrac|ONTRAC|DHL|LaserShip)\s*:\s*([A-Za-z0-9]+)',
            re.IGNORECASE
        )
        for p in soup.find_all('p'):
            p_text = CostcoParser._clean_text(p.get_text())
            match = carrier_line_pattern.search(p_text)
            if match:
                text_clean = match.group(1).upper().strip()
                if CostcoParser._is_valid_tracking(text_clean) and text_clean not in tracking_numbers:
                    tracking_numbers.append(text_clean)
                    logger.info(f"Extracted tracking from carrier line: {text_clean}")
        
        carrier_keywords = [
            'Tracking Number', 'tracking number',
            'United Parcel Service', 'UPS',
            'USPS', 'United States Postal',
            'OnTrac', 'ONTRAC',
            'DHL', 'Carrier'
        ]
        
        tds = soup.find_all('td', class_='align-column')
        for td in tds:
            td_text = td.get_text()
            is_carrier_label = any(kw in td_text for kw in carrier_keywords)
            if is_carrier_label and not td.find('a'):
                parent_tr = td.find_parent('tr')
                if parent_tr:
                    next_tr = parent_tr.find_next_sibling('tr')
                    if next_tr:
                        link = next_tr.find('a')
                        if link:
                            text = CostcoParser._clean_text(link.get_text())
                            if text and CostcoParser._is_valid_tracking(text):
                                text_clean = text.upper().strip()
                                if text_clean not in tracking_numbers:
                                    tracking_numbers.append(text_clean)
                                    logger.info(f"Extracted tracking from carrier label: {text_clean}")
        
        if not tracking_numbers:
            tracking_links = soup.find_all('a', href=lambda h: h and 'emailtracking' in h.lower())
            for link in tracking_links:
                text = CostcoParser._clean_text(link.get_text())
                if text and CostcoParser._is_valid_tracking(text):
                    text_clean = text.upper().strip()
                    if text_clean not in tracking_numbers:
                        tracking_numbers.append(text_clean)
                        logger.info(f"Extracted tracking from emailtracking link: {text_clean}")
        
        if not tracking_numbers:
            for td in tds:
                if 'Cancellation' in td.get_text() or 'Order Number' in td.get_text():
                    continue
                link = td.find('a', target='_blank')
                if link:
                    text = CostcoParser._clean_text(link.get_text())
                    if text and CostcoParser._is_valid_tracking(text):
                        text_clean = text.upper().strip()
                        if text_clean not in tracking_numbers:
                            tracking_numbers.append(text_clean)
                            logger.info(f"Extracted tracking from align-column: {text_clean}")
        
        if not tracking_numbers:
            page_text = soup.get_text()
            ups_matches = re.findall(r'1Z[A-Za-z0-9]{16}', page_text)
            for match in ups_matches:
                match_upper = match.upper()
                if match_upper not in tracking_numbers:
                    tracking_numbers.append(match_upper)
                    logger.info(f"Extracted UPS tracking from text: {match_upper}")

        if not tracking_numbers:
            all_links = soup.find_all('a', target='_blank')
            for link in all_links:
                href = link.get('href', '')
                if 'costco.com' in href.lower():
                    continue
                text = CostcoParser._clean_text(link.get_text())
                if text and CostcoParser._is_valid_tracking(text):
                    text_clean = text.upper().strip()
                    if text_clean not in tracking_numbers:
                        tracking_numbers.append(text_clean)
                        logger.info(f"Extracted tracking from target=_blank link: {text_clean}")
        
        if not tracking_numbers and html_content:
            tracking_numbers = CostcoParser._extract_tracking_regex_fallback(html_content)
        
        logger.info(f"Total tracking numbers found: {len(tracking_numbers)}")
        return tracking_numbers
    
    @staticmethod
    def _extract_tracking_regex_fallback(html_content: str) -> List[str]:
        tracking_numbers = []
        
        ups_pattern = r'1Z[A-Z0-9]{16}'
        ups_matches = re.findall(ups_pattern, html_content, re.IGNORECASE)
        for match in ups_matches:
            match_upper = match.upper()
            if CostcoParser._is_valid_tracking(match_upper) and match_upper not in tracking_numbers:
                tracking_numbers.append(match_upper)
                logger.info(f"Regex fallback - UPS tracking: {match_upper}")
        
        fedex_patterns = [
            r'\b\d{12}\b',
            r'\b\d{15}\b',
            r'\b\d{20}\b',
            r'\b\d{22}\b'
        ]
        for pattern in fedex_patterns:
            fedex_matches = re.findall(pattern, html_content)
            for match in fedex_matches:
                if CostcoParser._is_valid_tracking(match) and match not in tracking_numbers:
                    tracking_numbers.append(match)
                    logger.info(f"Regex fallback - FedEx tracking: {match}")
        
        usps_pattern = r'94\d{20,22}'
        usps_matches = re.findall(usps_pattern, html_content)
        for match in usps_matches:
            if CostcoParser._is_valid_tracking(match) and match not in tracking_numbers:
                tracking_numbers.append(match)
                logger.info(f"Regex fallback - USPS tracking: {match}")
        
        ontrac_pattern = r'C\d{14}'
        ontrac_matches = re.findall(ontrac_pattern, html_content, re.IGNORECASE)
        for match in ontrac_matches:
            match_upper = match.upper()
            if CostcoParser._is_valid_tracking(match_upper) and match_upper not in tracking_numbers:
                tracking_numbers.append(match_upper)
                logger.info(f"Regex fallback - OnTrac tracking: {match_upper}")
        
        lasership_pattern = r'L[A-Z]\d{8}'
        lasership_matches = re.findall(lasership_pattern, html_content, re.IGNORECASE)
        for match in lasership_matches:
            match_upper = match.upper()
            if CostcoParser._is_valid_tracking(match_upper) and match_upper not in tracking_numbers:
                tracking_numbers.append(match_upper)
                logger.info(f"Regex fallback - LaserShip tracking: {match_upper}")
        
        return tracking_numbers

    @staticmethod
    def _extract_product_image(section, title: str = '') -> str:
        def _is_product_src(src: str) -> bool:
            src_l = src.lower()
            if not src:
                return False
            if 'barcode' in src_l or 'tracking' in src_l or 'emailtracking' in src_l:
                return False
            if 'costco_wholesale' in src_l or 'logo' in src_l:
                return False
            return (
                'costco-static.com' in src_l
                or 'bfasset.costco' in src_l
                or ('wcsstore' in src_l and 'images' in src_l)
            )

        search_roots = [section]
        parent_td = section.find_parent('td')
        if parent_td:
            search_roots.append(parent_td)
        parent_tr = section.find_parent('tr')
        if parent_tr:
            search_roots.append(parent_tr)

        for root in search_roots:
            for img in root.find_all('img'):
                src = (img.get('src') or '').strip()
                if _is_product_src(src):
                    logger.debug("Extracted Costco product image: %s", src[:120])
                    return src

        if title:
            title_prefix = title[:40]
            soup = section.find_parent('html') or section
            for img in soup.find_all('img'):
                alt = (img.get('alt') or '').strip()
                src = (img.get('src') or '').strip()
                if not src or not alt or not _is_product_src(src):
                    continue
                if title_prefix in alt or alt[:40] in title:
                    logger.debug("Matched Costco product image by alt: %s", src[:120])
                    return src
        return ''

    @staticmethod
    def parse_product_details(html_content: str) -> Tuple[List[Dict[str, str]], str]:
        config = CostcoParser._load_config()
        soup = BeautifulSoup(html_content, 'lxml')
        products = []
        
        costco_config = config.get('costco_parsing', {})
        product_config = costco_config.get('product', {})
        
        item_sections = soup.find_all('div', class_='item-desc-column')
        if not item_sections:
            item_sections = soup.find_all('td', style=lambda s: s and 'display: inline-block' in s)
        
        for section in item_sections:
            product = {}
            
            title_td = section.find('td', style=lambda s: s and 'font-size: 14px' in s and 'line-height: 24px' in s)
            if title_td:
                product['title'] = CostcoParser._clean_text(title_td.get_text())
            
            tds = section.find_all('td')
            for td in tds:
                text = td.get_text()
                if 'Item #' in text or 'Item#' in text:
                    item_num = re.search(r'Item\s*#?\s*:?\s*(\d+)', text)
                    if item_num:
                        product['item_number'] = CostcoParser._clean_text(item_num.group(1))
                
                if 'Quantity' in text:
                    qty_match = re.search(r'Quantity\s*:?\s*(\d+)', text)
                    if qty_match:
                        product['quantity'] = qty_match.group(1)
                
                if '$' in text and 'price' not in product:
                    price_match = re.search(r'\$[\d,]+\.?\d*', text)
                    if price_match:
                        product['price'] = CostcoParser._normalize_price(price_match.group())
            
            if product.get('title'):
                if 'quantity' not in product:
                    product['quantity'] = '1'
                if 'price' not in product:
                    product['price'] = 'N/A'
                item_image = CostcoParser._extract_product_image(section, product.get('title', ''))
                if item_image:
                    product['item_image'] = item_image
                    logger.info("Scraped Costco product image for: %s", product['title'][:80])
                products.append(product)
                logger.debug(f"Extracted product: {product}")
        
        total_price = CostcoParser._extract_total_price(soup)
        
        return products, total_price

    @staticmethod
    def _extract_total_price(soup: BeautifulSoup) -> str:
        h2_tags = soup.find_all('h2')
        for h2 in h2_tags:
            h2_text = h2.get_text().strip()
            if h2_text == 'Total' or (h2_text.startswith('Total') and 'Subtotal' not in h2_text):
                parent_tr = h2.find_parent('tr')
                if parent_tr:
                    price_td = parent_tr.find('td', align='right')
                    if price_td:
                        price_text = CostcoParser._clean_text(price_td.get_text())
                        if '$' in price_text or price_text.replace('.', '').replace(',', '').isdigit():
                            return CostcoParser._normalize_price(price_text)
                    all_tds = parent_tr.find_all('td')
                    for td in all_tds:
                        td_text = td.get_text()
                        price_match = re.search(r'\$\s*[\d,]+\.?\d*', td_text)
                        if price_match:
                            return CostcoParser._normalize_price(price_match.group())
        
        page_text = soup.get_text()
        total_match = re.search(r'Total[:\s]*\$\s*[\d,]+\.?\d*', page_text)
        if total_match:
            price_match = re.search(r'\$\s*[\d,]+\.?\d*', total_match.group())
            if price_match:
                return CostcoParser._normalize_price(price_match.group())
        
        return 'N/A'

    @staticmethod
    def extract_price_summary(soup: BeautifulSoup) -> Dict[str, str]:
        summary = {
            'subtotal': 'N/A',
            'shipping': 'N/A',
            'tax': 'N/A',
            'total': 'N/A'
        }
        
        h2_tags = soup.find_all(['h2', 'h3'])
        for tag in h2_tags:
            text = tag.get_text()
            parent_tr = tag.find_parent('tr')
            if parent_tr:
                price_td = parent_tr.find('td', align='right')
                if price_td:
                    price = CostcoParser._clean_text(price_td.get_text())
                    price = CostcoParser._normalize_price(price)
                    
                    if 'Subtotal' in text:
                        summary['subtotal'] = price
                    elif 'Shipping' in text or 'Handling' in text:
                        summary['shipping'] = price
                    elif 'Tax' in text:
                        summary['tax'] = price
                    elif 'Total' in text:
                        summary['total'] = price
        
        logger.debug(f"Extracted price summary: {summary}")
        return summary

