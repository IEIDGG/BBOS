"""Exact USD decimal-to-minor-unit conversion."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def parse_usd_to_minor(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("USD amount must be decimal text")
    text = value.replace("$", "").replace(",", "").strip()
    if not text:
        raise ValueError("USD amount is empty")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("USD amount is malformed") from exc
    if not amount.is_finite():
        raise ValueError("USD amount must be finite")
    minor = amount * Decimal(100)
    if minor != minor.to_integral_value():
        raise ValueError("fractional cent is not supported")
    return int(minor)


class MoneyIntegrityError(ValueError):
    """Raised when persisted money representations are unsafe or disagree."""


class MoneyUnavailableError(ValueError):
    """Raised when no persisted money representation exists."""


@dataclass(frozen=True)
class ResolvedMoney:
    amount_minor: int
    currency_code: str
    source: str


def format_usd_minor(amount_minor: object) -> str:
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValueError("minor USD amount must be an integer")
    sign = "-" if amount_minor < 0 else ""
    whole, cents = divmod(abs(amount_minor), 100)
    return f"${sign}{whole}.{cents:02d}"


def resolve_usd_money(row: Mapping[str, object]) -> ResolvedMoney:
    """Resolve BBOS SQLite canonical and historical money without guessing."""

    if not isinstance(row, Mapping):
        raise MoneyIntegrityError("money row must be a mapping")
    canonical_amount = row.get("total_price_minor")
    canonical_currency = row.get("currency_code")
    canonical_present = canonical_amount is not None or canonical_currency is not None
    legacy_amount = row.get("total_price")
    legacy_present = legacy_amount is not None and str(legacy_amount).strip() != ""

    canonical = None
    if canonical_present:
        if (
            isinstance(canonical_amount, bool)
            or not isinstance(canonical_amount, int)
            or not isinstance(canonical_currency, str)
            or canonical_currency.strip().upper() != "USD"
        ):
            raise MoneyIntegrityError(
                "canonical money requires integer minor units and USD currency"
            )
        canonical = ResolvedMoney(canonical_amount, "USD", "canonical")

    legacy = None
    if legacy_present:
        try:
            parsed = parse_usd_to_minor(legacy_amount)
        except ValueError as exc:
            raise MoneyIntegrityError("legacy total_price is invalid") from exc
        legacy = ResolvedMoney(parsed, "USD", "legacy")

    if canonical is None and legacy is None:
        raise MoneyUnavailableError("order money is unavailable")
    if canonical is not None and legacy is not None:
        if canonical.amount_minor != legacy.amount_minor:
            raise MoneyIntegrityError("canonical and legacy order money disagree")
        return canonical
    return canonical or legacy


def display_order_total(row: Mapping[str, object]) -> str:
    return format_usd_minor(resolve_usd_money(row).amount_minor)
