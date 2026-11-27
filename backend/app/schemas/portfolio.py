"""Schemas for non-market assets and non-credit-card liabilities."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Money

AssetClass = Literal["cash", "fixed_deposit", "epf_ppf", "real_estate", "gold", "other"]
LiabilityType = Literal[
    "home_loan", "auto_loan", "personal_loan", "education_loan", "other"
]


class AssetCreate(BaseModel):
    """Payload to create a non-market asset."""

    name: str = Field(min_length=1, max_length=160)
    asset_class: AssetClass
    current_value: Money = Field(ge=0)
    valuation_date: date
    notes: str | None = Field(default=None, max_length=2000)


class AssetUpdate(BaseModel):
    """Partial update for a non-market asset."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    asset_class: AssetClass | None = None
    current_value: Money | None = Field(default=None, ge=0)
    valuation_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AssetRead(BaseModel):
    """Non-market asset with its latest user-entered valuation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    asset_class: AssetClass
    current_value: Money
    currency: str
    valuation_date: date
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LiabilityCreate(BaseModel):
    """Payload to create a term liability (credit cards are accounts, not liabilities)."""

    name: str = Field(min_length=1, max_length=160)
    liability_type: LiabilityType
    principal_outstanding: Money = Field(ge=0)
    interest_rate_annual: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=4)
    emi_amount: Money | None = Field(default=None, ge=0)
    as_of_date: date
    secured_asset_id: UUID | None = None


class LiabilityUpdate(BaseModel):
    """Partial update for a term liability."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    liability_type: LiabilityType | None = None
    principal_outstanding: Money | None = Field(default=None, ge=0)
    interest_rate_annual: Decimal | None = Field(
        default=None, ge=0, max_digits=7, decimal_places=4
    )
    emi_amount: Money | None = Field(default=None, ge=0)
    as_of_date: date | None = None
    secured_asset_id: UUID | None = None


class LiabilityRead(BaseModel):
    """Term liability with optional link to the secured asset."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    liability_type: LiabilityType
    principal_outstanding: Money
    interest_rate_annual: Decimal | None
    emi_amount: Money | None
    currency: str
    as_of_date: date
    secured_asset_id: UUID | None
    created_at: datetime
    updated_at: datetime
