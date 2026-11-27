"""Schemas for transaction listing, manual categorisation, and cash flow."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.categories import CategoryKind
from app.schemas.common import Money

Direction = Literal["debit", "credit"]
CategorisationSource = Literal["uncategorised", "rule", "manual"]


class TransactionRead(BaseModel):
    """Ledger row enriched with its category and account name."""

    id: UUID
    account_id: UUID
    account_name: str
    transaction_date: date
    direction: Direction
    amount: Money
    currency: str
    description_raw: str
    description_clean: str
    reference_number: str | None
    category_id: UUID | None
    category_name: str | None
    category_kind: CategoryKind | None
    categorisation_source: CategorisationSource
    is_transfer: bool
    import_batch_id: UUID | None
    created_at: datetime


class TransactionUpdate(BaseModel):
    """Fields a user may set manually on a transaction."""

    category_id: UUID | None = None
    is_transfer: bool | None = None


class TransactionList(BaseModel):
    """Paginated transactions plus money totals for the active filters."""

    items: list[TransactionRead]
    total: int
    limit: int
    offset: int
    credits: Money
    debits: Money
    net: Money
    transfers: Money


class CashFlowCategory(BaseModel):
    """Cash-flow contribution for one category."""

    category_id: UUID | None
    category_name: str
    kind: CategoryKind
    amount: Money
    transaction_count: int


class CashFlowRead(BaseModel):
    """Monthly income, expenses, and category breakdown with transfers excluded."""

    period_month: date
    income: Money
    expenses: Money
    net: Money
    savings_rate: float
    transfers_excluded: Money
    by_category: list[CashFlowCategory]


class BudgetCreate(BaseModel):
    """Payload to create a monthly category budget."""

    model_config = ConfigDict(json_schema_extra={"example": {"period_month": "2026-11-01"}})

    category_id: UUID
    period_month: date
    limit_amount: Money = Field(ge=0)

    @field_validator("period_month")
    @classmethod
    def first_of_month(cls, value: date) -> date:
        """Budgets are keyed to the first day of a month."""
        if value.day != 1:
            raise ValueError("period_month must be the first day of a month")
        return value


class BudgetUpdate(BaseModel):
    """Partial update for a budget limit."""

    limit_amount: Money = Field(ge=0)


class BudgetRead(BaseModel):
    """Budget with computed spend, remaining amount, and utilisation."""

    id: UUID
    category_id: UUID
    category_name: str
    period_month: date
    limit_amount: Money
    spent_amount: Money
    remaining_amount: Money
    variance_amount: Money
    percent_used: float
    is_over_budget: bool
    currency: str
    created_at: datetime
    updated_at: datetime
