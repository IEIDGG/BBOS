import json
import os
import re
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime


class CarrierDetector:
    @staticmethod
    def detect_carrier(tracking_number: str) -> str:
        tracking_number = tracking_number.strip().upper()
        
        if re.match(r'^1Z[A-Z0-9]{16}$', tracking_number):
            return "UPS"
        
        if re.match(r'^\d{12}$', tracking_number) or re.match(r'^\d{15}$', tracking_number) or re.match(r'^\d{20}$', tracking_number):
            return "FedEx"
        
        if re.match(r'^\d{22}$', tracking_number) or re.match(r'^\d{20}$', tracking_number):
            return "USPS"
        
        if re.match(r'^92\d{22}$', tracking_number) or re.match(r'^94\d{22}$', tracking_number) or re.match(r'^93\d{22}$', tracking_number):
            return "USPS"
        
        if re.match(r'^TBA\d{12}$', tracking_number):
            return "Amazon"
        
        if re.match(r'^\d{12,14}$', tracking_number):
            return "FedEx"
        
        if len(tracking_number) == 18 and tracking_number.startswith('1Z'):
            return "UPS"
        
        if re.match(r'^D\d{15}$', tracking_number):
            return "OnTrac"
        
        return "Undetermined"


class AddressExtractor:
    @staticmethod
    def extract_zip_from_state(state_and_zip: str) -> Optional[str]:
        if not state_and_zip:
            return None
        
        zip_match = re.search(r'\b\d{5}(?:-\d{4})?\b', state_and_zip)
        if zip_match:
            return zip_match.group(0)
        
        parts = state_and_zip.split()
        for part in parts:
            if re.match(r'^\d{5}(?:-\d{4})?$', part):
                return part
        
        return None
    
    @staticmethod
    def extract_state_from_state(state_and_zip: str) -> Optional[str]:
        if not state_and_zip:
            return None
        
        parts = state_and_zip.split()
        if parts:
            state_code = parts[0].upper()
            if len(state_code) == 2 and state_code.isalpha():
                return state_code
        
        return None


class APIConfig:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), 'api_config.json')
        
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Config file not found: {self.config_path}")
            return {
                "api_url": "http://localhost:8000",
                "api_key": "",
                "enabled": False,
                "zip_to_buying_group": {},
                "state_to_buying_group": {}
            }
        except json.JSONDecodeError as e:
            print(f"Error parsing config file: {e}")
            return {}
    
    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def is_enabled(self) -> bool:
        return self.config.get('enabled', False)
    
    def set_enabled(self, enabled: bool):
        self.config['enabled'] = enabled
        self.save_config()
    
    def get_api_url(self) -> str:
        return self.config.get('api_url', 'http://localhost:8000')
    
    def get_api_key(self) -> str:
        return self.config.get('api_key', '')
    
    def get_buying_group(self, zip_code: Optional[str], state_code: Optional[str]) -> Optional[str]:
        if zip_code:
            zip_5 = zip_code[:5] if len(zip_code) >= 5 else zip_code
            zip_mappings = self.config.get('zip_to_buying_group', {})
            if zip_5 in zip_mappings:
                return zip_mappings[zip_5]
        
        if state_code:
            state_mappings = self.config.get('state_to_buying_group', {})
            if state_code in state_mappings:
                return state_mappings[state_code]
        
        return None


class OrderAPISubmitter:
    def __init__(self, config: APIConfig = None):
        self.config = config or APIConfig()
        self.carrier_detector = CarrierDetector()
        self.address_extractor = AddressExtractor()
        self.submitted_orders = set()
    
    def check_api_health(self) -> Dict[str, Any]:
        api_url = self.config.get_api_url()
        
        try:
            endpoint = f"{api_url}/health"
            response = requests.get(endpoint, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status": data.get('status', 'unknown'),
                    "database": data.get('database', 'unknown'),
                    "message": "API is healthy"
                }
            else:
                return {
                    "success": False,
                    "status": "error",
                    "database": "unknown",
                    "message": f"HTTP {response.status_code}: {response.text}"
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "status": "timeout",
                "database": "unknown",
                "message": "Request timed out after 5 seconds"
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "status": "unreachable",
                "database": "unknown",
                "message": "Could not connect to API server"
            }
        except Exception as e:
            return {
                "success": False,
                "status": "error",
                "database": "unknown",
                "message": f"Error: {str(e)}"
            }
    
    def _prepare_order_payload(self, order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tracking_numbers = order.get('tracking', [])
        if not tracking_numbers:
            return None
        
        order_number = order.get('number') or order.get('order_number')
        if not order_number:
            return None
        
        state_info = order.get('state', '')
        zip_code = self.address_extractor.extract_zip_from_state(state_info)
        state_code = self.address_extractor.extract_state_from_state(state_info)
        
        buying_group = self.config.get_buying_group(zip_code, state_code)
        
        if not buying_group:
            return None
        
        order_date = order.get('date', '')
        try:
            if order_date:
                purchase_datetime = datetime.strptime(order_date, '%Y-%m-%d').isoformat()
            else:
                purchase_datetime = datetime.now().isoformat()
        except ValueError:
            purchase_datetime = datetime.now().isoformat()
        
        total_price = order.get('total_price', 'N/A')
        if isinstance(total_price, str):
            total_price = total_price.replace('$', '').replace(',', '')
            try:
                total_price = float(total_price)
            except ValueError:
                total_price = 0.0
        
        payloads = []
        for tracking_number in tracking_numbers:
            carrier = self.carrier_detector.detect_carrier(tracking_number)
            
            payload = {
                "website": "bestbuy",
                "order_id": order_number,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "purchase_datetime": purchase_datetime,
                "total_amount": total_price,
                "buying_group": buying_group,
                "metadata": {
                    "source": "bbos_continuous_monitor",
                    "zip_code": zip_code or "unknown",
                    "state_code": state_code or "unknown"
                }
            }
            payloads.append(payload)
        
        return payloads
    
    def submit_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.is_enabled():
            return {
                "success": False,
                "message": "API submission is disabled",
                "submitted": 0
            }
        
        order_number = order.get('number') or order.get('order_number')
        if not order_number:
            return {
                "success": False,
                "message": "Order number not found",
                "submitted": 0
            }
        
        tracking_numbers = order.get('tracking', [])
        if not tracking_numbers:
            return {
                "success": False,
                "message": "No tracking numbers found",
                "submitted": 0
            }
        
        payloads = self._prepare_order_payload(order)
        if not payloads:
            return {
                "success": False,
                "message": "Failed to prepare order payload",
                "submitted": 0
            }
        
        api_url = self.config.get_api_url()
        api_key = self.config.get_api_key()
        
        if not api_key:
            return {
                "success": False,
                "message": "API key not configured",
                "submitted": 0
            }
        
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        
        results = []
        submitted_count = 0
        
        for payload in payloads:
            tracking_number = payload['tracking_number']
            
            unique_key = f"{order_number}_{tracking_number}"
            if unique_key in self.submitted_orders:
                results.append({
                    "tracking_number": tracking_number,
                    "status": "skipped",
                    "message": "Already submitted in this session"
                })
                continue
            
            try:
                endpoint = f"{api_url}/bestbuy/submit-order"
                response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    response_data = response.json()
                    self.submitted_orders.add(unique_key)
                    submitted_count += 1
                    results.append({
                        "tracking_number": tracking_number,
                        "status": "success",
                        "message": response_data.get('message', 'Submitted successfully'),
                        "response": response_data
                    })
                else:
                    results.append({
                        "tracking_number": tracking_number,
                        "status": "failed",
                        "message": f"HTTP {response.status_code}: {response.text}",
                        "response": None
                    })
            except requests.exceptions.RequestException as e:
                results.append({
                    "tracking_number": tracking_number,
                    "status": "error",
                    "message": f"Request failed: {str(e)}",
                    "response": None
                })
        
        return {
            "success": submitted_count > 0,
            "message": f"Submitted {submitted_count}/{len(payloads)} tracking numbers",
            "submitted": submitted_count,
            "results": results
        }
    
    def submit_orders(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.config.is_enabled():
            return {
                "success": False,
                "message": "API submission is disabled",
                "total_submitted": 0,
                "total_orders": 0
            }
        
        total_submitted = 0
        total_orders = 0
        order_results = []
        
        for order in orders:
            order_number = order.get('number') or order.get('order_number')
            result = self.submit_order(order)
            
            if result.get('submitted', 0) > 0:
                total_submitted += result['submitted']
                total_orders += 1
            
            order_results.append({
                "order_number": order_number,
                "result": result
            })
        
        return {
            "success": total_submitted > 0,
            "message": f"Submitted {total_submitted} tracking numbers from {total_orders} orders",
            "total_submitted": total_submitted,
            "total_orders": total_orders,
            "order_results": order_results
        }
    
    def submit_orders_bulk(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.config.is_enabled():
            return {
                "success": False,
                "message": "API submission is disabled",
                "total_submitted": 0,
                "total_orders": 0
            }
        
        api_url = self.config.get_api_url()
        api_key = self.config.get_api_key()
        
        if not api_key:
            return {
                "success": False,
                "message": "API key not configured",
                "total_submitted": 0,
                "total_orders": 0
            }
        
        all_payloads = []
        for order in orders:
            payloads = self._prepare_order_payload(order)
            if payloads:
                all_payloads.extend(payloads)
        
        if not all_payloads:
            return {
                "success": False,
                "message": "No valid payloads to submit",
                "total_submitted": 0,
                "total_orders": 0
            }
        
        grouped_by_buying_group = {}
        for payload in all_payloads:
            buying_group = payload['buying_group']
            if buying_group not in grouped_by_buying_group:
                grouped_by_buying_group[buying_group] = []
            grouped_by_buying_group[buying_group].append(payload)
        
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        
        total_submitted = 0
        total_failed = 0
        group_results = []
        
        for buying_group, group_payloads in grouped_by_buying_group.items():
            filtered_payloads = []
            skipped = []
            
            for payload in group_payloads:
                order_number = payload['order_id']
                tracking_number = payload['tracking_number']
                unique_key = f"{order_number}_{tracking_number}"
                
                if unique_key in self.submitted_orders:
                    skipped.append({
                        "order_id": order_number,
                        "tracking_number": tracking_number,
                        "status": "skipped"
                    })
                else:
                    filtered_payloads.append(payload)
            
            if not filtered_payloads:
                if skipped:
                    group_results.append({
                        "buying_group": buying_group,
                        "total": len(skipped),
                        "successful": 0,
                        "failed": 0,
                        "skipped": len(skipped),
                        "message": "All orders already submitted",
                        "details": skipped
                    })
                continue
            
            batch_size = 50
            group_successful = 0
            group_failed = 0
            group_response_details = []
            group_errors = []
            
            for i in range(0, len(filtered_payloads), batch_size):
                batch_payloads = filtered_payloads[i:i + batch_size]
                
                try:
                    endpoint = f"{api_url}/bestbuy/submit-orders"
                    bulk_payload = {"orders": batch_payloads}
                    
                    response = requests.post(endpoint, json=bulk_payload, headers=headers, timeout=30)
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        successful = response_data.get('successful', 0)
                        failed = response_data.get('failed', 0)
                        
                        for payload in batch_payloads:
                            unique_key = f"{payload['order_id']}_{payload['tracking_number']}"
                            self.submitted_orders.add(unique_key)
                        
                        group_successful += successful
                        group_failed += failed
                        total_submitted += successful
                        total_failed += failed
                        
                        if 'results' in response_data:
                            group_response_details.extend(response_data['results'])
                    else:
                        group_failed += len(batch_payloads)
                        total_failed += len(batch_payloads)
                        group_errors.append(f"Batch {i//batch_size + 1}: HTTP {response.status_code}: {response.text}")
                except requests.exceptions.RequestException as e:
                    group_failed += len(batch_payloads)
                    total_failed += len(batch_payloads)
                    group_errors.append(f"Batch {i//batch_size + 1}: Request failed: {str(e)}")

            message = f"Submitted {group_successful}/{len(filtered_payloads)} orders successfully"
            if group_errors:
                message += f". Errors: {'; '.join(group_errors)}"
            
            group_results.append({
                "buying_group": buying_group,
                "total": len(filtered_payloads),
                "successful": group_successful,
                "failed": group_failed,
                "skipped": len(skipped),
                "message": message,
                "details": group_response_details
            })
        
        return {
            "success": total_submitted > 0,
            "message": f"Bulk submitted {total_submitted} tracking numbers across {len(group_results)} buying group(s)",
            "total_submitted": total_submitted,
            "total_failed": total_failed,
            "total_orders": len(all_payloads),
            "buying_groups": len(grouped_by_buying_group),
            "group_results": group_results
        }

    def run_interactive_bulk_test(self):
        from core.database import DatabaseManager
        from config.settings import DB_SETTINGS
        
        print("\n" + "="*60)
        print("          INTERACTIVE BULK SUBMISSION TEST")
        print("="*60)

        default_db = "bestbuy_orders.sqlite3"
        print(f"\nEnter database file path (default: {default_db})")
        db_path = input("> ").strip()
        
        if not db_path:
            db_path = default_db
            
        if not os.path.exists(db_path):
            print(f"\n✗ Error: Database file not found at: {db_path}")
            return

        try:
            db_config = DB_SETTINGS.copy()
            db_config['filename'] = db_path
            
            print(f"\nConnecting to database: {db_path}")
            db_manager = DatabaseManager(db_config=db_config)
            
            print("Fetching latest 2 orders with tracking information...")
            orders = db_manager.get_latest_orders(limit=2, with_tracking_only=True)
            
            if not orders:
                print("✗ No orders with tracking found in this database.")
                db_manager.close()
                return

            print(f"✓ Found {len(orders)} order(s).")
            for order in orders:
                print(f"  - Order {order.get('order_number', 'Unknown')}: {len(order.get('tracking', []))} tracking #s")

            print("\nSubmitting orders via Bulk API...")
            result = self.submit_orders_bulk(orders)
            
            print("\n" + "-"*60)
            if result['success']:
                print(f"✓ Status: SUCCESS")
                print(f"✓ Message: {result['message']}")
                print(f"✓ Total Submitted: {result['total_submitted']}")
                print(f"✓ Buying Groups: {result['buying_groups']}")
                
                if 'group_results' in result:
                    print("\nGroup Results:")
                    for group in result['group_results']:
                        print(f"  - {group['buying_group']}: {group['successful']} success, {group['failed']} failed")
            else:
                print(f"✗ Status: FAILED")
                print(f"✗ Message: {result['message']}")
                print(f"✗ Errors: {result.get('total_failed')} failed")
            print("-"*60)
            
            db_manager.close()

        except Exception as e:
            print(f"\n✗ Error running test: {str(e)}")
            import traceback
            traceback.print_exc()

