"""Shared Pydantic helpers, including precision-safe money serialisation."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from finpath_core.types import quantize_inr
from pydantic import PlainSerializer

Money = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(quantize_inr(value), "f"),
        return_type=str,
        when_used="json",
    ),
]
"""Decimal money that serialises to a fixed 4-decimal string (never a float)."""
