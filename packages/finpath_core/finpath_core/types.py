"""Shared domain types and Decimal precision helpers."""

from decimal import ROUND_HALF_UP, Decimal

INR = "INR"
MONEY_QUANT = Decimal("0.0001")


def quantize_inr(value: Decimal) -> Decimal:
    """Round a Decimal monetary amount to 4 decimal places using HALF_UP."""
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
