"""Account CRUD and derived-balance queries."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinancialAccount, FinancialTransaction
from app.schemas.accounts import AccountCreate, AccountRead, AccountType, AccountUpdate


class AccountHasTransactionsError(Exception):
    """Raised when deleting an account would silently discard transactions."""

    def __init__(self, transaction_count: int) -> None:
        self.transaction_count = transaction_count
        super().__init__(f"Account has {transaction_count} transaction(s)")


class DuplicateAccountError(Exception):
    """Raised when an active account with the same name/institution already exists."""


async def _totals_by_account(
    session: AsyncSession, user_id: UUID
) -> dict[UUID, tuple[Decimal, int]]:
    """Return derived credits/debits and transaction counts keyed by account id."""
    credit_sum = func.coalesce(
        func.sum(
            case(
                (FinancialTransaction.direction == "credit", FinancialTransaction.amount),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    debit_sum = func.coalesce(
        func.sum(
            case(
                (FinancialTransaction.direction == "debit", FinancialTransaction.amount),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    stmt = (
        select(
            FinancialTransaction.account_id,
            credit_sum.label("credits"),
            debit_sum.label("debits"),
            func.count(FinancialTransaction.id).label("transaction_count"),
        )
        .where(FinancialTransaction.user_id == user_id)
        .group_by(FinancialTransaction.account_id)
    )
    rows = (await session.execute(stmt)).all()
    return {
        row.account_id: (Decimal(row.credits) - Decimal(row.debits), int(row.transaction_count))
        for row in rows
    }


def _to_read(
    account: FinancialAccount, net_change: Decimal, transaction_count: int
) -> AccountRead:
    return AccountRead(
        id=account.id,
        name=account.name,
        account_type=cast(AccountType, account.account_type),
        institution_name=account.institution_name,
        masked_account_number=account.masked_account_number,
        currency=account.currency,
        opening_balance=account.opening_balance,
        opening_balance_date=account.opening_balance_date,
        is_active=account.is_active,
        derived_balance=Decimal(account.opening_balance) + net_change,
        transaction_count=transaction_count,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


async def list_accounts(
    session: AsyncSession, user_id: UUID, *, include_inactive: bool = True
) -> list[AccountRead]:
    """List a user's accounts with balances derived from the transaction ledger."""
    stmt = select(FinancialAccount).where(FinancialAccount.user_id == user_id)
    if not include_inactive:
        stmt = stmt.where(FinancialAccount.is_active.is_(True))
    stmt = stmt.order_by(
        FinancialAccount.is_active.desc(),
        FinancialAccount.account_type,
        FinancialAccount.name,
    )
    accounts = (await session.execute(stmt)).scalars().all()
    totals = await _totals_by_account(session, user_id)
    return [
        _to_read(account, *totals.get(account.id, (Decimal("0"), 0))) for account in accounts
    ]


async def get_account(
    session: AsyncSession, user_id: UUID, account_id: UUID
) -> AccountRead | None:
    """Fetch one account (RLS also prevents cross-user access)."""
    account = (
        await session.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return None
    totals = await _totals_by_account(session, user_id)
    return _to_read(account, *totals.get(account.id, (Decimal("0"), 0)))


async def create_account(
    session: AsyncSession, user_id: UUID, payload: AccountCreate
) -> AccountRead:
    """Create an account, returning 409-style duplicate errors to the API layer."""
    account = FinancialAccount(
        user_id=user_id,
        name=payload.name.strip(),
        account_type=payload.account_type,
        institution_name=(payload.institution_name or "").strip() or None,
        masked_account_number=(payload.masked_account_number or "").strip() or None,
        opening_balance=payload.opening_balance,
        opening_balance_date=payload.opening_balance_date,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateAccountError from exc
    await session.refresh(account)
    return _to_read(account, Decimal("0"), 0)


async def update_account(
    session: AsyncSession, user_id: UUID, account_id: UUID, payload: AccountUpdate
) -> AccountRead | None:
    """Apply a partial update to an account owned by ``user_id``."""
    account = (
        await session.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return None

    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = str(changes["name"]).strip()
    if "institution_name" in changes:
        raw_institution = changes["institution_name"]
        changes["institution_name"] = (
            str(raw_institution).strip() if raw_institution else None
        )
    if "masked_account_number" in changes:
        raw_number = changes["masked_account_number"]
        changes["masked_account_number"] = str(raw_number).strip() if raw_number else None

    for field_name, value in changes.items():
        setattr(account, field_name, value)

    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateAccountError from exc
    await session.refresh(account)

    totals = await _totals_by_account(session, user_id)
    return _to_read(account, *totals.get(account.id, (Decimal("0"), 0)))


async def delete_account(
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    confirm_delete_transactions: bool,
) -> bool:
    """Delete an account, refusing to cascade transactions unless explicitly confirmed."""
    account = (
        await session.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return False

    transaction_count = int(
        (
            await session.execute(
                select(func.count(FinancialTransaction.id)).where(
                    FinancialTransaction.account_id == account.id,
                    FinancialTransaction.user_id == user_id,
                )
            )
        ).scalar_one()
    )
    if transaction_count > 0 and not confirm_delete_transactions:
        raise AccountHasTransactionsError(transaction_count)

    await session.delete(account)
    await session.flush()
    return True
