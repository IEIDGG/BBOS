"""Local UI adapter for direct IEIDLLC scanned-order persistence."""

import json
import os
from collections.abc import Mapping
from typing import Any, Dict, List, Protocol

from core.scanned_order_writer import ScannedOrderWriter


class APIConfig:
    """Preserve the existing local sender toggle without HTTP configuration."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "api_config.json"
        )
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path) as config_file:
                loaded = json.load(config_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"enabled": False}
        return {"enabled": bool(loaded.get("enabled", False))}

    def save_config(self) -> None:
        with open(self.config_path, "w") as config_file:
            json.dump(self.config, config_file, indent=4)

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def set_enabled(self, enabled: bool) -> None:
        self.config["enabled"] = enabled
        self.save_config()


class OrderWriter(Protocol):
    def health(self) -> dict[str, object]: ...

    def write_order(self, order: Mapping[str, object]) -> dict[str, object]: ...


class OrderAPISubmitter:
    """Compatibility name for the direct PostgreSQL scanned-order writer."""

    def __init__(
        self, config: APIConfig | None = None, writer: OrderWriter | None = None
    ) -> None:
        self.config = config or APIConfig()
        self._writer = writer

    def _direct_writer(self) -> OrderWriter:
        if self._writer is None:
            self._writer = ScannedOrderWriter()
        return self._writer

    def check_api_health(self) -> Dict[str, Any]:
        try:
            return self._direct_writer().health()
        except Exception as exc:
            return {
                "success": False,
                "status": "error",
                "database": "unavailable",
                "message": str(exc),
            }

    def submit_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._direct_writer().write_order(order)
        except Exception as exc:
            return {"success": False, "message": str(exc), "submitted": 0}

    def submit_orders(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.submit_orders_bulk(orders)

    def submit_orders_bulk(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_submitted = 0
        total_failed = 0
        order_results = []
        for order in orders:
            result = self.submit_order(order)
            submitted = int(result.get("submitted", 0) or 0)
            total_submitted += submitted
            if not result.get("success"):
                total_failed += 1
            order_results.append(
                {
                    "order_number": order.get("number") or order.get("order_number"),
                    "result": result,
                }
            )
        return {
            "success": total_submitted > 0,
            "message": f"Stored {total_submitted}/{len(orders)} scanned orders",
            "total_submitted": total_submitted,
            "total_failed": total_failed,
            "total_orders": len(orders),
            "order_results": order_results,
        }

    def run_interactive_bulk_test(self) -> None:
        from config.settings import DB_SETTINGS
        from core.database import DatabaseManager

        default_db = "db/bestbuy_orders.sqlite3"
        print(f"\nEnter database file path (default: {default_db})")
        db_path = input("> ").strip() or default_db
        if not os.path.exists(db_path):
            print(f"\nError: Database file not found at: {db_path}")
            return
        db_config: dict[str, Any] = dict(DB_SETTINGS)
        db_config["filename"] = db_path
        db_manager = DatabaseManager(db_config=db_config)
        try:
            orders = db_manager.get_latest_orders(limit=2, with_tracking_only=True)
            result = self.submit_orders_bulk(orders)
            print(result["message"])
        finally:
            db_manager.close()
