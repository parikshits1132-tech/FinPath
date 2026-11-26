"""Tests proving PostgreSQL Row-Level Security (RLS) and schema constraints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.db.models import (
    Asset,
    Budget,
    CategorisationRule,
    FinancialAccount,
    FinancialTransaction,
    ImportBatch,
    ImportRowError,
    Liability,
    NetWorthSnapshot,
    TransactionCategory,
)
from app.db.session import get_session_factory, set_rls_user_id
from tests.conftest import register_and_login


@pytest.mark.asyncio
async def test_finpath_app_role_is_non_superuser_and_nobypassrls() -> None:
    """Confirm the app DB role cannot bypass PostgreSQL RLS."""
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        assert row.current_user == "finpath_app"
        assert row.rolsuper is False
        assert row.rolbypassrls is False


@pytest.mark.asyncio
async def test_derived_account_balance_schema_and_asset_liability_constraints(
    client: AsyncClient,
) -> None:
    """Verify financial_accounts omits current_balance and asset/liability checks reject invalid."""
    user_a, _ = await register_and_login(client, "constraints@example.com")
    factory = get_session_factory()

    async with factory() as session:
        cols = await session.run_sync(
            lambda sync_sess: [
                c["name"] for c in inspect(sync_sess.bind).get_columns("financial_accounts")
            ]
        )
        assert "opening_balance" in cols
        assert "current_balance" not in cols

    # Assets must reject equity, mutual_fund, crypto
    for disallowed_class in ("equity", "mutual_fund", "crypto"):
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await set_rls_user_id(session, user_a)
                    session.add(
                        Asset(
                            user_id=user_a,
                            name="Invalid Asset",
                            asset_class=disallowed_class,
                            current_value=Decimal("1000.0000"),
                            valuation_date=date(2026, 11, 1),
                        )
                    )

    # Liabilities must reject credit_card
    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await set_rls_user_id(session, user_a)
                session.add(
                    Liability(
                        user_id=user_a,
                        name="Invalid Card Liability",
                        liability_type="credit_card",
                        principal_outstanding=Decimal("5000.0000"),
                        as_of_date=date(2026, 11, 1),
                    )
                )


@pytest.mark.asyncio
async def test_rls_fail_closed_and_cross_user_isolation(client: AsyncClient) -> None:
    """Prove User A's records across all 10 RLS tables are completely invisible to User B."""
    user_a, _ = await register_and_login(client, "user_a@example.com", full_name="User A")
    user_b, _ = await register_and_login(client, "user_b@example.com", full_name="User B")
    factory = get_session_factory()

    # 1. Fail-closed when app.current_user_id is NOT set
    async with factory() as session, session.begin():
        rows = (await session.execute(select(FinancialAccount))).scalars().all()
        assert rows == []

    async with factory() as session:
        with pytest.raises(ProgrammingError):
            async with session.begin():
                session.add(
                    Asset(
                        user_id=user_a,
                        name="Unscoped Write",
                        asset_class="gold",
                        current_value=Decimal("50000.0000"),
                        valuation_date=date(2026, 11, 1),
                    )
                )

    # 2. Populate all 10 user-scoped tables as User A
    async with factory() as session, session.begin():
        await set_rls_user_id(session, user_a)

        sys_cat = (
            await session.execute(
                select(TransactionCategory).where(
                    TransactionCategory.is_system.is_(True),
                    TransactionCategory.name == "Groceries",
                )
            )
        ).scalar_one()

        custom_cat = TransactionCategory(
            user_id=user_a, name="A Custom Pet Care", kind="expense", is_system=False
        )
        account = FinancialAccount(
            user_id=user_a,
            name="HDFC Savings",
            account_type="savings",
            institution_name="HDFC Bank",
            opening_balance=Decimal("25000.0000"),
            opening_balance_date=date(2026, 1, 1),
        )
        session.add_all([custom_cat, account])
        await session.flush()

        batch = ImportBatch(
            user_id=user_a,
            account_id=account.id,
            parser_name="sample_bank_csv",
            file_name="stmt.csv",
            file_sha256="a" * 64,
            raw_object_key=f"raw/{user_a}/stmt.csv",
            file_size_bytes=512,
            status="completed",
        )
        session.add(batch)
        await session.flush()

        session.add_all(
            [
                CategorisationRule(
                    user_id=user_a,
                    keyword="zepto",
                    match_type="contains",
                    category_id=sys_cat.id,
                ),
                ImportRowError(
                    user_id=user_a,
                    import_batch_id=batch.id,
                    row_number=2,
                    error_code="BAD_DATE",
                    error_message="Unparseable date",
                    raw_row={"date": "invalid"},
                ),
                FinancialTransaction(
                    user_id=user_a,
                    account_id=account.id,
                    import_batch_id=batch.id,
                    transaction_date=date(2026, 11, 10),
                    direction="debit",
                    amount=Decimal("450.0000"),
                    description_raw="UPI-ZEPTO-GROCERIES",
                    description_clean="Zepto Groceries",
                    category_id=sys_cat.id,
                    categorisation_source="rule",
                    fingerprint="f" * 64,
                ),
                Budget(
                    user_id=user_a,
                    category_id=sys_cat.id,
                    period_month=date(2026, 11, 1),
                    limit_amount=Decimal("12000.0000"),
                ),
                Asset(
                    user_id=user_a,
                    name="Emergency FD",
                    asset_class="fixed_deposit",
                    current_value=Decimal("200000.0000"),
                    valuation_date=date(2026, 11, 1),
                ),
                Liability(
                    user_id=user_a,
                    name="Home Loan",
                    liability_type="home_loan",
                    principal_outstanding=Decimal("1500000.0000"),
                    as_of_date=date(2026, 11, 1),
                ),
                NetWorthSnapshot(
                    user_id=user_a,
                    snapshot_month=date(2026, 11, 1),
                    accounts_cash_total=Decimal("24550.0000"),
                    accounts_debt_total=Decimal("0.0000"),
                    assets_total=Decimal("200000.0000"),
                    liabilities_total=Decimal("1500000.0000"),
                    total_assets=Decimal("224550.0000"),
                    total_liabilities=Decimal("1500000.0000"),
                    net_worth=Decimal("-1275450.0000"),
                    breakdown={"note": "user_a"},
                ),
            ]
        )

    # 3. Verify User B sees ZERO of User A's rows and cannot update/delete them
    async with factory() as session, session.begin():
        await set_rls_user_id(session, user_b)

        for model in (
            FinancialAccount,
            CategorisationRule,
            ImportBatch,
            ImportRowError,
            FinancialTransaction,
            Budget,
            Asset,
            Liability,
            NetWorthSnapshot,
        ):
            found = (await session.execute(select(model))).scalars().all()
            assert found == [], f"RLS leak detected on {model.__tablename__}"

        # User B sees system categories, NOT User A's custom category
        cats = (await session.execute(select(TransactionCategory))).scalars().all()
        assert len(cats) >= 18
        assert all(c.is_system for c in cats)
        assert all(c.name != "A Custom Pet Care" for c in cats)

        # User B cannot update or delete User A's assets or system categories
        upd_res = await session.execute(
            update(Asset).where(Asset.user_id == user_a).values(name="Hacked")
        )
        assert upd_res.rowcount == 0
        del_res = await session.execute(delete(Asset).where(Asset.user_id == user_a))
        assert del_res.rowcount == 0
        sys_del = await session.execute(
            delete(TransactionCategory).where(TransactionCategory.is_system.is_(True))
        )
        assert sys_del.rowcount == 0
