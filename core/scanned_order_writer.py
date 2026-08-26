"""Direct BBOS persistence into IEIDLLC's shared scanned_orders table."""

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.money import parse_usd_to_minor


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    owner_id: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PostgresSettings":
        values = environ if environ is not None else os.environ
        required = {
            "host": "POSTGRES_HOST",
            "port": "POSTGRES_PORT",
            "database": "POSTGRES_DB",
            "user": "POSTGRES_USER",
            "password": "POSTGRES_PASSWORD",
            "owner_id": "IEIDLLC_USER_ID",
        }
        missing = [
            env_name for env_name in required.values() if not values.get(env_name)
        ]
        if missing:
            raise ValueError(f"missing PostgreSQL settings: {', '.join(missing)}")
        try:
            port = int(values[required["port"]])
        except ValueError as exc:
            raise ValueError("POSTGRES_PORT must be an integer") from exc
        return cls(
            host=values[required["host"]],
            port=port,
            database=values[required["database"]],
            user=values[required["user"]],
            password=values[required["password"]],
            owner_id=values[required["owner_id"]],
        )

    def connection_kwargs(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }


def _default_connect(**kwargs: object):
    import psycopg2

    return psycopg2.connect(**kwargs)


class ScannedOrderWriter:
    def __init__(
        self,
        *,
        settings: PostgresSettings | None = None,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings or PostgresSettings.from_env()
        self._connect = connect or _default_connect

    def health(self) -> dict[str, object]:
        connection = self._connect(**self.settings.connection_kwargs())
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT 1")
            ready = cursor.fetchone() == (1,)
            return {
                "success": ready,
                "status": "healthy" if ready else "error",
                "database": "connected" if ready else "unavailable",
                "message": "PostgreSQL is healthy"
                if ready
                else "PostgreSQL health check failed",
            }
        finally:
            cursor.close()
            connection.close()

    def write_order(self, order: Mapping[str, object]) -> dict[str, object]:
        order_number = str(
            order.get("number") or order.get("order_number") or ""
        ).strip()
        tracking_values = order.get("tracking")
        tracking_numbers = (
            [str(value).strip() for value in tracking_values if str(value).strip()]
            if isinstance(tracking_values, (list, tuple))
            else []
        )
        if not order_number:
            return {
                "success": False,
                "message": "Order number not found",
                "submitted": 0,
            }
        if not tracking_numbers:
            return {
                "success": False,
                "message": "No tracking numbers found",
                "submitted": 0,
            }
        try:
            amount_minor = parse_usd_to_minor(order.get("total_price"))
        except ValueError as exc:
            return {"success": False, "message": str(exc), "submitted": 0}

        raw = json.dumps(dict(order), sort_keys=True, separators=(",", ":"))
        connection = self._connect(**self.settings.connection_kwargs())
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO public.scanned_orders (
                    user_id, provider, source_key, tracking_number,
                    amount_minor, currency_code, raw, ingest_source,
                    record_schema_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'api', 1)
                ON CONFLICT (user_id, provider, source_key)
                WHERE source_key IS NOT NULL AND btrim(source_key) <> ''
                DO UPDATE SET
                    tracking_number = EXCLUDED.tracking_number,
                    amount_minor = EXCLUDED.amount_minor,
                    currency_code = EXCLUDED.currency_code,
                    raw = EXCLUDED.raw,
                    ingest_source = EXCLUDED.ingest_source,
                    record_schema_version = EXCLUDED.record_schema_version
                """,
                (
                    self.settings.owner_id,
                    "bbos",
                    order_number,
                    tracking_numbers[0],
                    amount_minor,
                    "USD",
                    raw,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()
        return {
            "success": True,
            "message": "Stored 1 scanned order",
            "submitted": 1,
            "tracking_number": tracking_numbers[0],
        }
