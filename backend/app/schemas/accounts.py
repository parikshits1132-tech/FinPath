"""Pydantic schemas for financial account CRUD."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Money

AccountType = Literal["checking", "savings", "credit_card", "cash", "wallet"]


class AccountBase(BaseModel):
    """Editable account attributes shared by create and update payloads."""

    name: str = Field(min_length=1, max_length=120)
    account_type: AccountType
    institution_name: str | None = Field(default=None, max_length=160)
    masked_account_number: str | None = Field(default=None, max_length=32)
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    opening_balance_date: date


class AccountCreate(AccountBase):
    """Payload to create a financial account."""


class AccountUpdate(BaseModel):
    """Fields allowed on a partial account update."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    account_type: AccountType | None = None
    institution_name: str | None = Field(default=None, max_length=160)
    masked_account_number: str | None = Field(default=None, max_length=32)
    opening_balance: Decimal | None = Field(
        default=None, max_digits=18, decimal_places=4
    )
    opening_balance_date: date | None = None
    is_active: bool | None = None


class AccountRead(BaseModel):
    """Account representation with the derived balance computed from transactions."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    account_type: AccountType
    institution_name: str | None
    masked_account_number: str | None
    currency: str
    opening_balance: Money
    opening_balance_date: date
    is_active: bool
    derived_balance: Money
    transaction_count: int
    created_at: datetime
    updated_at: datetime
