"""SQLAlchemy 2.0 ORM models for the 11 MVP tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all FinPath OLTP tables."""


class User(Base):
    """Registered FinPath user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("base_currency = 'INR'", name="ck_users_base_currency_inr"),)


class FinancialAccount(Base):
    """User bank, credit card, cash, or wallet account (balance is derived, never stored)."""

    __tablename__ = "financial_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    institution_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    masked_account_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    opening_balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "account_type IN ('checking','savings','credit_card','cash','wallet')",
            name="ck_financial_accounts_type",
        ),
        CheckConstraint("currency = 'INR'", name="ck_financial_accounts_currency_inr"),
        Index(
            "uq_accounts_active_name",
            "user_id",
            text("lower(name)"),
            text("COALESCE(lower(institution_name), '')"),
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_financial_accounts_user_type", "user_id", "account_type"),
    )


class TransactionCategory(Base):
    """System or user-defined transaction category."""

    __tablename__ = "transaction_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('income','expense','transfer')",
            name="ck_transaction_categories_kind",
        ),
        Index(
            "uq_categories_scope_name_kind",
            text("COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            text("lower(name)"),
            "kind",
            unique=True,
        ),
    )


class CategorisationRule(Base):
    """Deterministic keyword rule for transaction categorisation."""

    __tablename__ = "categorisation_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="contains")
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("match_type IN ('contains','exact')", name="ck_categorisation_rules_match"),
        Index("ix_rules_user_active_prio", "user_id", "is_active", "priority"),
    )


class ImportBatch(Base):
    """Metadata and MinIO lineage for each uploaded statement import."""

    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_accounts.id", ondelete="CASCADE"), nullable=False
    )
    parser_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_parquet_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inserted_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="ck_import_batches_file_size"),
        CheckConstraint(
            "status IN ('pending','processing','completed','partial_failed','failed')",
            name="ck_import_batches_status",
        ),
        Index("ix_import_batches_user_sha", "user_id", "file_sha256"),
        Index("ix_import_batches_user_created", "user_id", text("created_at DESC")),
    )


class ImportRowError(Base):
    """Row-level import validation failures awaiting resolution."""

    __tablename__ = "import_row_errors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    corrected_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "resolution_status IN ('open','corrected','ignored')",
            name="ck_import_row_errors_status",
        ),
        Index(
            "ix_import_row_errors_batch_status",
            "user_id",
            "import_batch_id",
            "resolution_status",
        ),
    )


class FinancialTransaction(Base):
    """Canonical transaction ledger row with deterministic deduplication fingerprint."""

    __tablename__ = "financial_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_accounts.id", ondelete="CASCADE"), nullable=False
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    description_clean: Mapped[str] = mapped_column(Text, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    categorisation_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="uncategorised"
    )
    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("direction IN ('debit','credit')", name="ck_financial_tx_direction"),
        CheckConstraint("amount > 0", name="ck_financial_tx_amount_pos"),
        CheckConstraint("currency = 'INR'", name="ck_financial_tx_currency_inr"),
        CheckConstraint(
            "categorisation_source IN ('uncategorised','rule','manual')",
            name="ck_financial_tx_cat_source",
        ),
        UniqueConstraint("user_id", "fingerprint", name="uq_financial_tx_user_fingerprint"),
        Index("ix_financial_tx_user_date", "user_id", text("transaction_date DESC")),
        Index(
            "ix_financial_tx_user_account_date",
            "user_id",
            "account_id",
            text("transaction_date DESC"),
        ),
        Index(
            "ix_financial_tx_user_cat_date",
            "user_id",
            "category_id",
            text("transaction_date DESC"),
        ),
    )


class Budget(Base):
    """Monthly spending budget per user and category."""

    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("EXTRACT(DAY FROM period_month) = 1", name="ck_budgets_first_of_month"),
        CheckConstraint("limit_amount >= 0", name="ck_budgets_limit_nonneg"),
        CheckConstraint("currency = 'INR'", name="ck_budgets_currency_inr"),
        UniqueConstraint(
            "user_id",
            "category_id",
            "period_month",
            name="uq_budgets_user_cat_month",
        ),
    )


class Asset(Base):
    """Non-market assets (excludes equity, mutual_fund, crypto in MVP)."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    asset_class: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "asset_class IN ('cash','fixed_deposit','epf_ppf','real_estate','gold','other')",
            name="ck_assets_class_mvp",
        ),
        CheckConstraint("current_value >= 0", name="ck_assets_value_nonneg"),
        CheckConstraint("currency = 'INR'", name="ck_assets_currency_inr"),
        Index("ix_assets_user_class", "user_id", "asset_class"),
    )


class Liability(Base):
    """Term and non-card liabilities (credit cards live only in financial_accounts)."""

    __tablename__ = "liabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    secured_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    liability_type: Mapped[str] = mapped_column(Text, nullable=False)
    principal_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    interest_rate_annual: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    emi_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "liability_type IN ('home_loan','auto_loan','personal_loan','education_loan','other')",
            name="ck_liabilities_type_no_cc",
        ),
        CheckConstraint("principal_outstanding >= 0", name="ck_liabilities_principal_nonneg"),
        CheckConstraint(
            "interest_rate_annual IS NULL OR interest_rate_annual >= 0",
            name="ck_liabilities_rate_nonneg",
        ),
        CheckConstraint("emi_amount IS NULL OR emi_amount >= 0", name="ck_liabilities_emi_nonneg"),
        CheckConstraint("currency = 'INR'", name="ck_liabilities_currency_inr"),
        Index("ix_liabilities_user_type", "user_id", "liability_type"),
    )


class NetWorthSnapshot(Base):
    """Monthly incremental net worth snapshot."""

    __tablename__ = "net_worth_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_month: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    accounts_cash_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    accounts_debt_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    assets_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    liabilities_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_assets: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_liabilities: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_incremental: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "EXTRACT(DAY FROM snapshot_month) = 1", name="ck_net_worth_snapshots_first_of_month"
        ),
        CheckConstraint("currency = 'INR'", name="ck_net_worth_snapshots_currency_inr"),
        UniqueConstraint("user_id", "snapshot_month", name="uq_net_worth_user_month"),
    )
