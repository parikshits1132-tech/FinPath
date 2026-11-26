"""Configure non-superuser app role and force PostgreSQL Row-Level Security.

Revision ID: 0002_rls_policies
Revises: 0001_initial_mvp_schema
Create Date: 2026-11-25 17:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_rls_policies"
down_revision: str | Sequence[str] | None = "0001_initial_mvp_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_SCOPED_TABLES = (
    "financial_accounts",
    "categorisation_rules",
    "import_batches",
    "import_row_errors",
    "financial_transactions",
    "budgets",
    "assets",
    "liabilities",
    "net_worth_snapshots",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finpath_app') THEN
                CREATE ROLE finpath_app LOGIN PASSWORD 'finpath_app_dev_password'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO finpath_app;")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO finpath_app;"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO finpath_app;")

    for table in USER_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_user_isolation ON {table}
                FOR ALL
                TO finpath_app
                USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
                WITH CHECK (
                    user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                );
            """
        )

    # transaction_categories allows reading shared system rows (user_id IS NULL),
    # while writes are strictly scoped to the owning user and non-system rows.
    op.execute("ALTER TABLE transaction_categories ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE transaction_categories FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY transaction_categories_select ON transaction_categories
            FOR SELECT
            TO finpath_app
            USING (
                user_id IS NULL
                OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            );
        """
    )
    op.execute(
        """
        CREATE POLICY transaction_categories_insert ON transaction_categories
            FOR INSERT
            TO finpath_app
            WITH CHECK (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                AND is_system = false
            );
        """
    )
    op.execute(
        """
        CREATE POLICY transaction_categories_update ON transaction_categories
            FOR UPDATE
            TO finpath_app
            USING (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                AND is_system = false
            )
            WITH CHECK (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                AND is_system = false
            );
        """
    )
    op.execute(
        """
        CREATE POLICY transaction_categories_delete ON transaction_categories
            FOR DELETE
            TO finpath_app
            USING (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                AND is_system = false
            );
        """
    )


def downgrade() -> None:
    for policy in (
        "transaction_categories_delete",
        "transaction_categories_update",
        "transaction_categories_insert",
        "transaction_categories_select",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON transaction_categories;")
    op.execute("ALTER TABLE transaction_categories NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE transaction_categories DISABLE ROW LEVEL SECURITY;")

    for table in reversed(USER_SCOPED_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_user_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
