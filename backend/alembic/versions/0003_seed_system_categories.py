"""Seed default Indian personal-finance system transaction categories.

Revision ID: 0003_seed_system_categories
Revises: 0002_rls_policies
Create Date: 2026-11-25 17:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_seed_system_categories"
down_revision: str | Sequence[str] | None = "0002_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Salary", "income"),
    ("Freelance & Consulting", "income"),
    ("Interest & Dividends", "income"),
    ("Other Income", "income"),
    ("Rent & Housing", "expense"),
    ("Groceries", "expense"),
    ("Dining & Food Delivery", "expense"),
    ("Utilities & Bills", "expense"),
    ("Fuel & Transport", "expense"),
    ("Shopping", "expense"),
    ("Healthcare", "expense"),
    ("Insurance", "expense"),
    ("Loan EMI", "expense"),
    ("Subscriptions & Entertainment", "expense"),
    ("Education", "expense"),
    ("Travel", "expense"),
    ("Miscellaneous", "expense"),
    ("Self Transfer & Card Payment", "transfer"),
)


def upgrade() -> None:
    for name, kind in SYSTEM_CATEGORIES:
        escaped_name = name.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO transaction_categories (user_id, name, kind, is_system)
            VALUES (NULL, '{escaped_name}', '{kind}', true)
            ON CONFLICT DO NOTHING;
            """
        )


def downgrade() -> None:
    op.execute("DELETE FROM transaction_categories WHERE user_id IS NULL AND is_system = true;")
