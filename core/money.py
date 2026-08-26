"""Exact USD decimal-to-minor-unit conversion."""

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
