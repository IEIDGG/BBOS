import re
import logging
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AmazonParser:
    ORDER_ID_PATTERN = re.compile(r'\b\d{3}-\d{7}-\d{7}\b')

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return ''
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _normalize_price(price_str: str) -> str:
        if not price_str:
            return ''
        price_str = re.sub(r'[^\d.,]', '', price_str)
        return f'${price_str}' if price_str else ''

    @staticmethod
    def _parse_price_to_float(price_str: str) -> float:
        if not price_str:
            return 0.0
        clean = re.sub(r'[^\d.]', '', price_str)
        try:
            return float(clean)
        except ValueError:
            return 0.0

    @classmethod
    def extract_order_number(cls, soup: BeautifulSoup, subject: str = None) -> Optional[str]:
        if subject:
            match = cls.ORDER_ID_PATTERN.search(subject)
            if match:
                logger.debug(f"Extracted order number from subject: {match.group()}")
                return match.group()

        text_content = soup.get_text()
        order_marker = text_content.find('Order #')
        if order_marker != -1:
            search_area = text_content[order_marker:order_marker + 50]
            match = cls.ORDER_ID_PATTERN.search(search_area)
            if match:
                logger.debug(f"Extracted order number from HTML Order #: {match.group()}")
                return match.group()

        match = cls.ORDER_ID_PATTERN.search(text_content)
        if match:
            logger.debug(f"Extracted order number via regex fallback: {match.group()}")
            return match.group()

        return None

    @classmethod
    def extract_recipient_location(cls, soup: BeautifulSoup) -> Optional[str]:
        for bold in soup.find_all(['b', 'strong']):
            text = cls._clean_text(bold.get_text())
            if ' - ' in text and ',' in text:
                parts = text.split(' - ')
                if len(parts) == 2:
                    location = parts[1]
                    if re.search(r',\s*[A-Z]{2}$', location):
                        logger.debug(f"Extracted recipient/location: {text}")
                        return text

        for td in soup.find_all('td'):
            text = cls._clean_text(td.get_text())
            if ' - ' in text and re.search(r',\s*[A-Z]{2}$', text):
                name_loc = text.split('\n')[0] if '\n' in text else text
                if ' - ' in name_loc:
                    logger.debug(f"Extracted recipient/location from td: {name_loc}")
                    return name_loc

        return None

    @classmethod
    def extract_state_from_location(cls, location_text: str) -> Optional[str]:
        if not location_text:
            return None
        match = re.search(r',\s*([A-Z]{2})$', location_text)
        if match:
            return match.group(1)
        return None

    @classmethod
    def extract_track_package_link(cls, soup: BeautifulSoup) -> Optional[str]:
        track_text_patterns = [
            'track package', 'track your package', 'track shipment', 
            'track your shipment', 'track delivery', 'see where your package is',
            'view delivery status', 'shipment status'
        ]
        track_url_patterns = [
            'ship-track', 'progress-tracker', 'tracking', 'shipment-tracking',
            'delivery-details', 'shipment-details', 'track'
        ]
        
        for a in soup.find_all('a', href=True):
            text = cls._clean_text(a.get_text()).lower()
            href = a['href']
            
            if any(kw in text for kw in track_text_patterns):
                logger.debug(f"Extracted track package link from text: {href}")
                return href
        
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(pattern in href for pattern in track_url_patterns):
                if 'amazon.com' in href or 'amzn' in href:
                    logger.debug(f"Extracted track package link from URL pattern: {a['href']}")
                    return a['href']
        
        return None

    @classmethod
    def extract_all_track_package_links(cls, soup: BeautifulSoup) -> List[Dict[str, str]]:
        from urllib.parse import unquote
        
        tracking_data = []
        seen_shipment_ids = set()
        
        track_text_patterns = [
            'track package', 'track your package', 'track shipment', 
            'track your shipment', 'track delivery', 'see where your package is',
            'view delivery status', 'shipment status'
        ]
        track_url_patterns = [
            'ship-track', 'progress-tracker', 'shipment-tracking',
            'delivery-details', 'shipment-details'
        ]
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = cls._clean_text(a.get_text()).lower()
            
            is_track_link = any(kw in text for kw in track_text_patterns)
            if not is_track_link:
                href_lower = href.lower()
                is_track_link = any(pattern in href_lower for pattern in track_url_patterns) and ('amazon.com' in href_lower or 'amzn' in href_lower)
            
            if is_track_link:
                decoded_link = unquote(href)
                shipment_match = None
                patterns = [
                    r'shipmentId[=:]([A-Za-z0-9]+)',
                    r'shipmentId%3D([A-Za-z0-9]+)',
                    r'packageId[=:]([A-Za-z0-9]+)',
                ]
                for pattern in patterns:
                    match = re.search(pattern, href, re.IGNORECASE)
                    if match:
                        shipment_match = match.group(1)
                        break
                
                if not shipment_match:
                    for pattern in patterns:
                        match = re.search(pattern, decoded_link, re.IGNORECASE)
                        if match:
                            shipment_match = match.group(1)
                            break
                
                if shipment_match and shipment_match not in seen_shipment_ids:
                    seen_shipment_ids.add(shipment_match)
                    tracking_data.append({
                        'tracking_number': shipment_match,
                        'tracking_url': href
                    })
                    logger.debug(f"Extracted tracking: {shipment_match} with URL")
        
        return tracking_data

    @classmethod
    def extract_tracking_from_link(cls, track_link: str) -> List[str]:
        tracking_numbers = []
        if not track_link:
            return tracking_numbers
        
        from urllib.parse import unquote
        decoded_link = unquote(track_link)
        
        patterns = [
            r'trackingId[=:]([A-Za-z0-9]+)',
            r'tracking[_-]?number[=:]([A-Za-z0-9]+)',
            r'packageId[=:]([A-Za-z0-9]+)',
            r'shipmentId[=:]([A-Za-z0-9]+)',
            r'shipmentId%3D([A-Za-z0-9]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, decoded_link, re.IGNORECASE)
            if match:
                tracking_id = match.group(1)
                if tracking_id not in tracking_numbers:
                    tracking_numbers.append(tracking_id)
                    logger.debug(f"Extracted tracking/shipment ID from URL: {tracking_id}")
        
        return tracking_numbers

    @classmethod
    def extract_tracking_numbers_from_html(cls, soup: BeautifulSoup) -> List[str]:
        tracking_numbers = []
        text_content = soup.get_text()
        
        carrier_patterns = [
            r'(?:UPS|USPS|FedEx|DHL|OnTrac)\s*(?:tracking|#|number)?[:\s]*([A-Z0-9]{10,30})',
            r'(?:Tracking|Carrier|Package)\s*(?:#|number|ID)?[:\s]*([A-Z0-9]{12,30})',
            r'\b(1Z[A-Z0-9]{16})\b',
            r'\b([0-9]{20,22})\b',
            r'\b([0-9]{12,15})\b',
            r'\b(C[0-9]{14})\b',
        ]
        
        for pattern in carrier_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                if match not in tracking_numbers and len(match) >= 10:
                    tracking_numbers.append(match)
                    logger.debug(f"Extracted tracking number from HTML: {match}")
        
        return tracking_numbers[:3]

    @classmethod
    def _extract_asin_from_url(cls, href: str) -> Optional[str]:
        asin_match = re.search(r'(?:/dp/|/gp/product/|/gp/aw/d/)([A-Z0-9]{10})', href)
        if asin_match:
            return asin_match.group(1)
        
        decoded_match = re.search(r'[?&]U=([^&]+)', href)
        if decoded_match:
            from urllib.parse import unquote
            decoded_url = unquote(decoded_match.group(1))
            asin_match = re.search(r'(?:/dp/|/gp/product/|/gp/aw/d/)([A-Z0-9]{10})', decoded_url)
            if asin_match:
                return asin_match.group(1)
        
        return None

    @classmethod
    def _is_sponsored_product(cls, link) -> bool:
        href = link.get('href', '').lower()
        sponsored_url_patterns = [
            '_spon_', '_rec_', '_recs_', 'spon=', 'rec=',
            'sponsored', 'recommendation', 'pf_rd_p'
        ]
        for pattern in sponsored_url_patterns:
            if pattern in href:
                logger.debug(f"Detected sponsored URL pattern: {pattern}")
                return True
        
        sponsored_keywords = [
            'sponsored', 'recommendation', 'you might also like', 
            'based on your', 'customers who bought', 'related to items',
            'inspired by', 'top picks', 'more items to explore',
            'frequently bought together', 'customers also bought'
        ]
        
        for ancestor in link.parents:
            if ancestor.name in ['table', 'div', 'td']:
                ancestor_text = ancestor.get_text().lower()[:1000]
                for keyword in sponsored_keywords:
                    if keyword in ancestor_text:
                        if 'quantity' not in ancestor_text and 'qty' not in ancestor_text:
                            logger.debug(f"Detected sponsored section keyword: {keyword}")
                            return True
            if ancestor.name == 'body':
                break
        
        return False
    
    @classmethod
    def _extract_price_from_element(cls, element) -> str:
        html_str = str(element)
        sup_patterns = [
            r'<sup[^>]*>\s*\$\s*</sup>\s*(\d+)\s*<sup[^>]*>\s*(\d+)\s*</sup>',
            r'<sup[^>]*>\$</sup>(\d+)<sup[^>]*>(\d+)</sup>',
            r'\$</sup>\s*(\d[\d,]*)\s*<sup[^>]*>(\d{2})',
        ]
        for sup_pattern in sup_patterns:
            sup_match = re.search(sup_pattern, html_str, re.IGNORECASE)
            if sup_match:
                dollars = sup_match.group(1).replace(',', '')
                cents = sup_match.group(2)
                return f'${dollars}.{cents}'
        
        aria_match = re.search(r'aria-label="[^"]*amount=(\d+)', html_str)
        if aria_match:
            amount = int(aria_match.group(1))
            return f'${amount // 100}.{amount % 100:02d}' if amount >= 100 else f'${amount}.00'
        
        text = element.get_text()
        price_match = re.search(r'\$[\d,]+\.?\d*', text)
        if price_match:
            return cls._normalize_price(price_match.group())
        
        return ''

    @classmethod
    def _calculate_item_total(cls, unit_price: str, quantity: str) -> str:
        price_float = cls._parse_price_to_float(unit_price)
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            qty = 1
        total = price_float * qty
        return f'${total:.2f}'

    @classmethod
    def extract_products(cls, soup: BeautifulSoup) -> List[Dict]:
        products = []
        seen_asins = set()
        
        all_links = soup.find_all('a', href=True)
        product_links = []
        for link in all_links:
            href = link.get('href', '')
            if '/dp/' in href or '/gp/product/' in href or '/gp/aw/d/' in href:
                product_links.append(link)
            elif '/gp/r.html' in href and 'dp%2F' in href:
                product_links.append(link)
        
        for link in product_links:
            href = link.get('href', '')
            asin = cls._extract_asin_from_url(href)
            if not asin:
                continue
            
            if asin in seen_asins:
                continue
            
            if cls._is_sponsored_product(link):
                logger.debug(f"Skipping sponsored product: {asin}")
                continue
            
            seen_asins.add(asin)

            title = cls._clean_text(link.get_text())
            
            img = link.find('img')
            if img:
                img_alt = img.get('alt', '') or img.get('title', '')
                img_alt = cls._clean_text(img_alt)
                if img_alt and len(img_alt) > len(title):
                    title = img_alt
            
            if not title or len(title) < 3:
                parent = link.find_parent('td') or link.find_parent('tr')
                if parent:
                    for sibling in parent.find_next_siblings(['td', 'div']):
                        text = cls._clean_text(sibling.get_text())
                        if text and len(text) > 10 and not text.startswith('$') and 'Quantity' not in text:
                            title = text[:200]
                            break

            if not title or len(title) < 3:
                continue

            title_with_asin = f"{title} {asin}" if asin else title

            product = {
                'title': title_with_asin,
                'asin': asin,
                'item_url': href,
                'quantity': '1',
                'unit_price': '',
                'price': ''
            }

            product_row = link.find_parent('tr')
            if not product_row:
                product_row = link.find_parent('table')
            
            if product_row:
                row_html = str(product_row)
                row_text = product_row.get_text()
                
                qty_patterns = [
                    r'Quantity:\s*(\d+)',
                    r'Qty:\s*(\d+)',
                    r'Qty\s*:\s*(\d+)',
                    r'Qty\s+(\d+)',
                    r'x\s*(\d+)',
                    r'×\s*(\d+)',
                    r'\((\d+)\s*item',
                    r'(\d+)\s*x\s*\$',
                ]
                for pattern in qty_patterns:
                    qty_match = re.search(pattern, row_text, re.IGNORECASE)
                    if qty_match:
                        qty_val = qty_match.group(1)
                        if int(qty_val) > 0 and int(qty_val) < 100:
                            product['quantity'] = qty_val
                            logger.debug(f"Found quantity {product['quantity']} for {asin}")
                            break
                
                price_divs = product_row.find_all('div', class_=lambda x: x and 'rio-text' in str(x))
                if not price_divs:
                    price_divs = product_row.find_all('span', attrs={'role': 'region'})
                
                for price_div in price_divs:
                    extracted_price = cls._extract_price_from_element(price_div)
                    if extracted_price:
                        product['unit_price'] = extracted_price
                        logger.debug(f"Found unit price {extracted_price} for {asin}")
                        break
                
                if not product['unit_price']:
                    product['unit_price'] = cls._extract_price_from_element(product_row)
            
            if product['unit_price']:
                product['price'] = cls._calculate_item_total(product['unit_price'], product['quantity'])
            else:
                product['price'] = ''

            products.append(product)
            logger.debug(f"Extracted product: {product['title'][:50]}... qty={product['quantity']}, unit=${product['unit_price']}, total={product['price']}")

        if not products:
            products = cls._extract_products_from_tables(soup)
        
        if not products:
            products = cls._extract_products_text_fallback(soup)
        
        return products
    
    @classmethod
    def _extract_products_from_tables(cls, soup: BeautifulSoup) -> List[Dict]:
        products = []
        
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    for cell in cells:
                        links = cell.find_all('a', href=True)
                        for link in links:
                            href = link.get('href', '')
                            if '/dp/' in href or '/gp/product/' in href:
                                if cls._is_sponsored_product(link):
                                    continue
                                title = None
                                img = cell.find('img')
                                if img:
                                    title = img.get('alt', '') or img.get('title', '')
                                
                                if not title:
                                    for other_cell in cells:
                                        text = cls._clean_text(other_cell.get_text())
                                        if text and len(text) > 10 and not text.startswith('$') and 'Quantity' not in text and 'Qty' not in text:
                                            title = text[:200]
                                            break
                                
                                if title and len(title) >= 3:
                                    asin = cls._extract_asin_from_url(href)
                                    clean_title = cls._clean_text(title)
                                    title_with_asin = f"{clean_title} {asin}" if asin else clean_title
                                    product = {
                                        'title': title_with_asin,
                                        'asin': asin or '',
                                        'item_url': href,
                                        'quantity': '1',
                                        'unit_price': '',
                                        'price': ''
                                    }
                                    
                                    row_text = row.get_text()
                                    qty_patterns = [
                                        r'(?:Quantity|Qty)[:\s]*(\d+)',
                                        r'x\s*(\d+)',
                                        r'×\s*(\d+)',
                                        r'\((\d+)\s*item',
                                    ]
                                    for pattern in qty_patterns:
                                        qty_match = re.search(pattern, row_text, re.IGNORECASE)
                                        if qty_match:
                                            qty_val = qty_match.group(1)
                                            if int(qty_val) > 0 and int(qty_val) < 100:
                                                product['quantity'] = qty_val
                                                break
                                    
                                    unit_price = cls._extract_price_from_element(row)
                                    if unit_price:
                                        product['unit_price'] = unit_price
                                        product['price'] = cls._calculate_item_total(unit_price, product['quantity'])
                                    
                                    products.append(product)
                                    logger.debug(f"Extracted product from table: {product['title'][:50]}...")
        
        return products
    
    @classmethod
    def _extract_products_text_fallback(cls, soup: BeautifulSoup) -> List[Dict]:
        products = []
        text_content = soup.get_text()
        
        for img in soup.find_all('img'):
            alt_text = img.get('alt', '').strip()
            if alt_text and len(alt_text) > 15 and 'amazon' not in alt_text.lower():
                parent_link = img.find_parent('a')
                item_url = ''
                asin = None
                if parent_link and parent_link.get('href'):
                    if cls._is_sponsored_product(parent_link):
                        continue
                    href = parent_link.get('href', '')
                    if 'amazon.com' in href or '/dp/' in href or '/gp/' in href:
                        item_url = href
                        asin = cls._extract_asin_from_url(href)
                
                title = alt_text[:200]
                title_with_asin = f"{title} {asin}" if asin else title
                product = {
                    'title': title_with_asin,
                    'asin': asin or '',
                    'item_url': item_url,
                    'quantity': '1',
                    'unit_price': '',
                    'price': ''
                }
                
                parent_row = img.find_parent('tr')
                if parent_row:
                    row_text = parent_row.get_text()
                    qty_patterns = [
                        r'(?:Quantity|Qty)[:\s]*(\d+)',
                        r'x\s*(\d+)',
                        r'×\s*(\d+)',
                        r'\((\d+)\s*item',
                    ]
                    for pattern in qty_patterns:
                        qty_match = re.search(pattern, row_text, re.IGNORECASE)
                        if qty_match:
                            qty_val = qty_match.group(1)
                            if int(qty_val) > 0 and int(qty_val) < 100:
                                product['quantity'] = qty_val
                                break
                    
                    unit_price = cls._extract_price_from_element(parent_row)
                    if unit_price:
                        product['unit_price'] = unit_price
                        product['price'] = cls._calculate_item_total(unit_price, product['quantity'])
                
                if product['title'] not in [p['title'] for p in products]:
                    products.append(product)
                    logger.debug(f"Extracted product from image alt: {product['title'][:50]}...")
        
        if not products:
            quantity_sections = re.findall(r'Quantity:\s*\d+[^$]*\$[\d,]+\.?\d*', text_content, re.IGNORECASE | re.DOTALL)
            for section in quantity_sections[:5]:
                qty_match = re.search(r'Quantity:\s*(\d+)', section, re.IGNORECASE)
                price_match = re.search(r'\$[\d,]+\.?\d*', section)
                if qty_match and price_match:
                    unit_price = cls._normalize_price(price_match.group())
                    quantity = qty_match.group(1)
                    product = {
                        'title': 'Amazon Product',
                        'asin': '',
                        'item_url': '',
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'price': cls._calculate_item_total(unit_price, quantity)
                    }
                    products.append(product)
                    logger.debug(f"Extracted product from text pattern: qty={product['quantity']}, price={product['price']}")
        
        return products

    @classmethod
    def extract_grand_total(cls, soup: BeautifulSoup) -> Optional[str]:
        for td in soup.find_all('td'):
            text = cls._clean_text(td.get_text())
            if text == 'Grand Total:' or text == 'Total:' or text == 'Total' or text == 'Grand Total' or text == 'Order Total':
                parent_row = td.find_parent('tr')
                if parent_row:
                    sibling_tds = parent_row.find_all('td')
                    for sibling in sibling_tds:
                        if sibling == td:
                            continue
                        sibling_text = sibling.get_text()
                        price_match = re.search(r'\$[\d,]+\.?\d*', sibling_text)
                        if price_match:
                            total = cls._normalize_price(price_match.group())
                            logger.debug(f"Extracted total from table: {total}")
                            return total
                next_td = td.find_next_sibling('td')
                if next_td:
                    next_text = next_td.get_text()
                    price_match = re.search(r'\$[\d,]+\.?\d*', next_text)
                    if price_match:
                        total = cls._normalize_price(price_match.group())
                        logger.debug(f"Extracted total from sibling td: {total}")
                        return total

        for table in soup.find_all('table'):
            table_text = table.get_text()
            if 'Total' in table_text:
                total_match = re.search(r'Total\s*\$[\d,]+\.?\d*', table_text)
                if total_match:
                    price_match = re.search(r'\$[\d,]+\.?\d*', total_match.group())
                    if price_match:
                        total = cls._normalize_price(price_match.group())
                        logger.debug(f"Extracted total from table text: {total}")
                        return total

        text_content = soup.get_text()
        total_patterns = [
            r'Grand Total:?\s*\$[\d,]+\.?\d*',
            r'Total:?\s*\$[\d,]+\.?\d*',
            r'Order Total:?\s*\$[\d,]+\.?\d*'
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                price_match = re.search(r'\$[\d,]+\.?\d*', match.group())
                if price_match:
                    total = cls._normalize_price(price_match.group())
                    logger.debug(f"Extracted total via regex: {total}")
                    return total

        return None

    @classmethod
    def parse_confirmation_email(cls, html_content: str, subject: str = None) -> Dict:
        soup = BeautifulSoup(html_content, 'lxml')

        order_number = cls.extract_order_number(soup, subject)
        if not order_number:
            logger.warning("Could not extract Amazon order number")
            return {}

        recipient_location = cls.extract_recipient_location(soup)
        state = cls.extract_state_from_location(recipient_location)
        products = cls.extract_products(soup)
        grand_total = cls.extract_grand_total(soup)

        logger.info(f"Amazon confirmation - Order: {order_number}, Products: {len(products)}, Total: {grand_total}")
        if not products:
            logger.warning(f"No products extracted for Amazon order {order_number}")
            all_links = soup.find_all('a', href=True)
            product_link_count = sum(1 for a in all_links if '/dp/' in a.get('href', '') or '/gp/product/' in a.get('href', ''))
            logger.debug(f"Found {product_link_count} product links in HTML")

        return {
            'order_number': order_number,
            'state': state or '',
            'products': products,
            'total_price': grand_total or 'N/A'
        }

    @classmethod
    def parse_cancellation_email(cls, html_content: str, subject: str = None) -> Dict:
        soup = BeautifulSoup(html_content, 'lxml')

        order_number = cls.extract_order_number(soup, subject)
        if not order_number:
            logger.warning("Could not extract Amazon cancellation order number")
            return {}

        return {
            'order_number': order_number,
            'status': 'Cancelled'
        }

    @classmethod
    def parse_shipped_email(cls, html_content: str, subject: str = None) -> Dict:
        soup = BeautifulSoup(html_content, 'lxml')

        order_number = cls.extract_order_number(soup, subject)
        if not order_number:
            logger.warning("Could not extract Amazon shipped order number")
            return {}

        recipient_location = cls.extract_recipient_location(soup)
        state = cls.extract_state_from_location(recipient_location)
        track_package_link = cls.extract_track_package_link(soup)
        products = cls.extract_products(soup)
        total = cls.extract_grand_total(soup)

        tracking_with_links = cls.extract_all_track_package_links(soup)
        
        tracking_numbers = [t['tracking_number'] for t in tracking_with_links]
        
        if not tracking_numbers:
            if track_package_link:
                tracking_numbers = cls.extract_tracking_from_link(track_package_link)
            if not tracking_numbers:
                tracking_numbers = cls.extract_tracking_numbers_from_html(soup)

        logger.debug(f"Shipped email - Order: {order_number}, Products: {len(products)}, Tracking: {tracking_numbers}")

        return {
            'order_number': order_number,
            'state': state or '',
            'track_package_link': track_package_link,
            'tracking_numbers': tracking_numbers,
            'tracking_with_links': tracking_with_links,
            'products': products,
            'total_price': total or 'N/A',
            'status': 'Shipped'
        }

    @classmethod
    def is_confirmation_email(cls, from_addr: str, subject: str) -> bool:
        from_match = 'auto-confirm@amazon.com' in from_addr.lower()
        subject_match = 'ordered' in subject.lower()
        return from_match and subject_match

    @classmethod
    def is_cancellation_email(cls, from_addr: str, subject: str) -> bool:
        cancel_senders = ['qla@amazon.com', 'order-update@amazon.com']
        from_match = any(sender in from_addr.lower() for sender in cancel_senders)
        subject_match = 'cancel' in subject.lower()
        return from_match or subject_match

    @classmethod
    def is_shipped_email(cls, from_addr: str, subject: str) -> bool:
        from_match = 'shipment-tracking@amazon.com' in from_addr.lower()
        subject_match = any(kw in subject.lower() for kw in ['shipped', 'arriving', 'package'])
        return from_match or subject_match

