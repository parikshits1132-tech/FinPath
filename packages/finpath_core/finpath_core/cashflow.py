"""Decimal-safe monthly period helpers and budget variance maths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finpath_core.types import quantize_inr


def first_of_month(value: date) -> date:
    """Return the first day of ``value``'s month."""
    return value.replace(day=1)


def month_bounds(period_month: date) -> tuple[date, date]:
    """Return the inclusive start and exclusive end for a month period."""
    if period_month.day != 1:
        raise ValueError("period_month must be the first day of a month")
    start = period_month
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, end


def previous_month(period_month: date) -> date:
    """Return the first day of the month before ``period_month``."""
    start = first_of_month(period_month)
    if start.month == 1:
        return date(start.year - 1, 12, 1)
    return date(start.year, start.month - 1, 1)


@dataclass(frozen=True)
class BudgetVariance:
    """Budget utilisation for one category and month."""

    limit_amount: Decimal
    spent_amount: Decimal
    remaining_amount: Decimal
    variance_amount: Decimal
    percent_used: float

    @property
    def is_over_budget(self) -> bool:
        """Return whether spending exceeded the limit."""
        return self.spent_amount > self.limit_amount


def budget_variance(limit_amount: Decimal, spent_amount: Decimal) -> BudgetVariance:
    """Compute remaining budget, variance, and utilisation percentage."""
    limit = quantize_inr(limit_amount)
    spent = quantize_inr(spent_amount)
    remaining = quantize_inr(limit - spent)
    if limit == 0:
        percent_used = 0.0 if spent <= 0 else 100.0
    else:
        percent_used = float((spent / limit) * Decimal(100))
    return BudgetVariance(
        limit_amount=limit,
        spent_amount=spent,
        remaining_amount=remaining,
        variance_amount=quantize_inr(-remaining),
        percent_used=round(percent_used, 2),
    )
