"""Create initial 11 MVP tables with NUMERIC money, constraints, and indexes.

Revision ID: 0001_initial_mvp_schema
Revises:
Create Date: 2026-11-25 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_mvp_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("base_currency = 'INR'", name="ck_users_base_currency_inr"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "financial_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("institution_name", sa.Text(), nullable=True),
        sa.Column("masked_account_number", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column(
            "opening_balance",
            sa.Numeric(precision=18, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("opening_balance_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "account_type IN ('checking','savings','credit_card','cash','wallet')",
            name="ck_financial_accounts_type",
        ),
        sa.CheckConstraint("currency = 'INR'", name="ck_financial_accounts_currency_inr"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_accounts_active_name",
        "financial_accounts",
        [
            "user_id",
            sa.text("lower(name)"),
            sa.text("COALESCE(lower(institution_name), '')"),
        ],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "ix_financial_accounts_user_type", "financial_accounts", ["user_id", "account_type"]
    )

    op.create_table(
        "transaction_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('income','expense','transfer')", name="ck_transaction_categories_kind"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["transaction_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_categories_scope_name_kind",
        "transaction_categories",
        [
            sa.text("COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            sa.text("lower(name)"),
            "kind",
        ],
        unique=True,
    )

    op.create_table(
        "categorisation_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), server_default="contains", nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "match_type IN ('contains','exact')", name="ck_categorisation_rules_match"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["transaction_categories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rules_user_active_prio",
        "categorisation_rules",
        ["user_id", "is_active", "priority"],
    )

    op.create_table(
        "import_batches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parser_name", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_object_key", sa.Text(), nullable=False),
        sa.Column("parsed_parquet_key", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inserted_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("file_size_bytes > 0", name="ck_import_batches_file_size"),
        sa.CheckConstraint(
            "status IN ('pending','processing','completed','partial_failed','failed')",
            name="ck_import_batches_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_user_sha", "import_batches", ["user_id", "file_sha256"])
    op.create_index(
        "ix_import_batches_user_created",
        "import_batches",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "import_row_errors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_row", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolution_status", sa.Text(), server_default="open", nullable=False),
        sa.Column("corrected_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resolution_status IN ('open','corrected','ignored')",
            name="ck_import_row_errors_status",
        ),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_row_errors_batch_status",
        "import_row_errors",
        ["user_id", "import_batch_id", "resolution_status"],
    )

    op.create_table(
        "financial_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("description_raw", sa.Text(), nullable=False),
        sa.Column("description_clean", sa.Text(), nullable=False),
        sa.Column("reference_number", sa.Text(), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "categorisation_source", sa.Text(), server_default="uncategorised", nullable=False
        ),
        sa.Column("is_transfer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("direction IN ('debit','credit')", name="ck_financial_tx_direction"),
        sa.CheckConstraint("amount > 0", name="ck_financial_tx_amount_pos"),
        sa.CheckConstraint("currency = 'INR'", name="ck_financial_tx_currency_inr"),
        sa.CheckConstraint(
            "categorisation_source IN ('uncategorised','rule','manual')",
            name="ck_financial_tx_cat_source",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["transaction_categories.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_financial_tx_user_fingerprint"),
    )
    op.create_index(
        "ix_financial_tx_user_date",
        "financial_transactions",
        ["user_id", sa.text("transaction_date DESC")],
    )
    op.create_index(
        "ix_financial_tx_user_account_date",
        "financial_transactions",
        ["user_id", "account_id", sa.text("transaction_date DESC")],
    )
    op.create_index(
        "ix_financial_tx_user_cat_date",
        "financial_transactions",
        ["user_id", "category_id", sa.text("transaction_date DESC")],
    )

    op.create_table(
        "budgets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("limit_amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("EXTRACT(DAY FROM period_month) = 1", name="ck_budgets_first_of_month"),
        sa.CheckConstraint("limit_amount >= 0", name="ck_budgets_limit_nonneg"),
        sa.CheckConstraint("currency = 'INR'", name="ck_budgets_currency_inr"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["transaction_categories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "category_id", "period_month", name="uq_budgets_user_cat_month"
        ),
    )

    op.create_table(
        "assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("current_value", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "asset_class IN ('cash','fixed_deposit','epf_ppf','real_estate','gold','other')",
            name="ck_assets_class_mvp",
        ),
        sa.CheckConstraint("current_value >= 0", name="ck_assets_value_nonneg"),
        sa.CheckConstraint("currency = 'INR'", name="ck_assets_currency_inr"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_user_class", "assets", ["user_id", "asset_class"])

    op.create_table(
        "liabilities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("secured_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("liability_type", sa.Text(), nullable=False),
        sa.Column("principal_outstanding", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("interest_rate_annual", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("emi_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "liability_type IN ('home_loan','auto_loan','personal_loan','education_loan','other')",
            name="ck_liabilities_type_no_cc",
        ),
        sa.CheckConstraint("principal_outstanding >= 0", name="ck_liabilities_principal_nonneg"),
        sa.CheckConstraint(
            "interest_rate_annual IS NULL OR interest_rate_annual >= 0",
            name="ck_liabilities_rate_nonneg",
        ),
        sa.CheckConstraint(
            "emi_amount IS NULL OR emi_amount >= 0", name="ck_liabilities_emi_nonneg"
        ),
        sa.CheckConstraint("currency = 'INR'", name="ck_liabilities_currency_inr"),
        sa.ForeignKeyConstraint(["secured_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_liabilities_user_type", "liabilities", ["user_id", "liability_type"])

    op.create_table(
        "net_worth_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_month", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("accounts_cash_total", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("accounts_debt_total", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("assets_total", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("liabilities_total", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("total_assets", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("total_liabilities", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_worth", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_incremental", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM snapshot_month) = 1",
            name="ck_net_worth_snapshots_first_of_month",
        ),
        sa.CheckConstraint("currency = 'INR'", name="ck_net_worth_snapshots_currency_inr"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "snapshot_month", name="uq_net_worth_user_month"),
    )


def downgrade() -> None:
    op.drop_table("net_worth_snapshots")
    op.drop_index("ix_liabilities_user_type", table_name="liabilities")
    op.drop_table("liabilities")
    op.drop_index("ix_assets_user_class", table_name="assets")
    op.drop_table("assets")
    op.drop_table("budgets")
    op.drop_index("ix_financial_tx_user_cat_date", table_name="financial_transactions")
    op.drop_index("ix_financial_tx_user_account_date", table_name="financial_transactions")
    op.drop_index("ix_financial_tx_user_date", table_name="financial_transactions")
    op.drop_table("financial_transactions")
    op.drop_index("ix_import_row_errors_batch_status", table_name="import_row_errors")
    op.drop_table("import_row_errors")
    op.drop_index("ix_import_batches_user_created", table_name="import_batches")
    op.drop_index("ix_import_batches_user_sha", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_rules_user_active_prio", table_name="categorisation_rules")
    op.drop_table("categorisation_rules")
    op.drop_index("uq_categories_scope_name_kind", table_name="transaction_categories")
    op.drop_table("transaction_categories")
    op.drop_index("ix_financial_accounts_user_type", table_name="financial_accounts")
    op.drop_index("uq_accounts_active_name", table_name="financial_accounts")
    op.drop_table("financial_accounts")
    op.drop_table("users")
