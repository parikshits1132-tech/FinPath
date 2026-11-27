"""Schemas for transaction categories, keyword rules, and retroactive application."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CategoryKind = Literal["income", "expense", "transfer"]
MatchType = Literal["contains", "exact"]


class CategoryCreate(BaseModel):
    """Payload to create a user-defined category."""

    name: str = Field(min_length=1, max_length=120)
    kind: CategoryKind
    parent_id: UUID | None = None


class CategoryUpdate(BaseModel):
    """Partial update for a user-defined category."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = None


class CategoryRead(BaseModel):
    """System or user-defined category."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: CategoryKind
    is_system: bool
    parent_id: UUID | None
    created_at: datetime


class RuleCreate(BaseModel):
    """Payload to create a deterministic keyword rule."""

    keyword: str = Field(min_length=1, max_length=120)
    match_type: MatchType = "contains"
    category_id: UUID
    priority: int = Field(default=100, ge=0, le=10_000)
    is_active: bool = True


class RuleUpdate(BaseModel):
    """Partial update for a keyword rule."""

    keyword: str | None = Field(default=None, min_length=1, max_length=120)
    match_type: MatchType | None = None
    category_id: UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


class RuleRead(BaseModel):
    """Keyword rule with denormalised category metadata."""

    id: UUID
    keyword: str
    match_type: MatchType
    category_id: UUID
    category_name: str
    category_kind: CategoryKind
    priority: int
    is_active: bool
    created_at: datetime


class ApplyRulesResult(BaseModel):
    """Counts returned after re-running rules over existing transactions."""

    scanned_transactions: int
    updated_transactions: int
    flagged_transfers: int
