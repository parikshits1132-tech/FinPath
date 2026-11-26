"""Unit tests for finpath_core Decimal helpers."""

from decimal import Decimal

from finpath_core import INR, quantize_inr


def test_quantize_inr() -> None:
    """INR amounts quantize to 4 decimal places using HALF_UP."""
    assert INR == "INR"
    assert quantize_inr(Decimal("1234.56785")) == Decimal("1234.5679")
    assert quantize_inr(Decimal("100")) == Decimal("100.0000")
