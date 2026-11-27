"""Transaction browsing, manual categorisation, and monthly cash-flow analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from finpath_core.cashflow import month_bounds
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinancialAccount, FinancialTransaction, TransactionCategory
from app.schemas.categories import CategoryKind
from app.schemas.transactions import (
    CashFlowCategory,
    CashFlowRead,
    CategorisationSource,
    Direction,
    TransactionList,
    TransactionRead,
    TransactionUpdate,
)
from app.services.categorisation import UnknownCategoryError, get_category


def _to_read(
    transaction: FinancialTransaction,
    account_name: str,
    category_name: str | None,
    category_kind: str | None,
) -> TransactionRead:
    return TransactionRead(
        id=transaction.id,
        account_id=transaction.account_id,
        account_name=account_name,
        transaction_date=transaction.transaction_date,
        direction=cast(Direction, transaction.direction),
        amount=transaction.amount,
        currency=transaction.currency,
        description_raw=transaction.description_raw,
        description_clean=transaction.description_clean,
        reference_number=transaction.reference_number,
        category_id=transaction.category_id,
        category_name=category_name,
        category_kind=cast(CategoryKind | None, category_kind),
        categorisation_source=cast(
            CategorisationSource, transaction.categorisation_source
        ),
        is_transfer=transaction.is_transfer,
        import_batch_id=transaction.import_batch_id,
        created_at=transaction.created_at,
    )


def _transaction_query() -> Any:
    """Build the shared ledger select with account and category metadata."""
    return (
        select(
            FinancialTransaction,
            FinancialAccount.name.label("account_name"),
            TransactionCategory.name.label("category_name"),
            TransactionCategory.kind.label("category_kind"),
        )
        .join(FinancialAccount, FinancialAccount.id == FinancialTransaction.account_id)
        .outerjoin(
            TransactionCategory,
            TransactionCategory.id == FinancialTransaction.category_id,
        )
    )


def _filters(
    *,
    user_id: UUID,
    account_id: UUID | None,
    category_id: UUID | None,
    direction: str | None,
    is_transfer: bool | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
) -> list[Any]:
    conditions: list[Any] = [FinancialTransaction.user_id == user_id]
    if account_id is not None:
        conditions.append(FinancialTransaction.account_id == account_id)
    if category_id is not None:
        conditions.append(FinancialTransaction.category_id == category_id)
    if direction is not None:
        conditions.append(FinancialTransaction.direction == direction)
    if is_transfer is not None:
        conditions.append(FinancialTransaction.is_transfer.is_(is_transfer))
    if date_from is not None:
        conditions.append(FinancialTransaction.transaction_date >= date_from)
    if date_to is not None:
        conditions.append(FinancialTransaction.transaction_date <= date_to)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            FinancialTransaction.description_clean.ilike(pattern)
            | FinancialTransaction.description_raw.ilike(pattern)
        )
    return conditions


async def list_transactions(
    session: AsyncSession,
    user_id: UUID,
    *,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    direction: str | None = None,
    is_transfer: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TransactionList:
    """Return a filtered, paginated ledger page with transfer-aware totals."""
    conditions = _filters(
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        direction=direction,
        is_transfer=is_transfer,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    stmt = (
        _transaction_query()
        .where(*conditions)
        .order_by(
            FinancialTransaction.transaction_date.desc(),
            FinancialTransaction.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        _to_read(transaction, account_name, category_name, category_kind)
        for transaction, account_name, category_name, category_kind in rows
    ]

    total = int(
        (
            await session.execute(
                select(func.count(FinancialTransaction.id)).where(*conditions)
            )
        ).scalar_one()
    )

    credit_sum = func.coalesce(
        func.sum(
            case(
                (
                    (FinancialTransaction.direction == "credit")
                    & (FinancialTransaction.is_transfer.is_(False)),
                    FinancialTransaction.amount,
                ),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    debit_sum = func.coalesce(
        func.sum(
            case(
                (
                    (FinancialTransaction.direction == "debit")
                    & (FinancialTransaction.is_transfer.is_(False)),
                    FinancialTransaction.amount,
                ),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    transfer_sum = func.coalesce(
        func.sum(
            case(
                (FinancialTransaction.is_transfer.is_(True), FinancialTransaction.amount),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    credits, debits, transfers = (
        await session.execute(select(credit_sum, debit_sum, transfer_sum).where(*conditions))
    ).one()
    credits = Decimal(credits)
    debits = Decimal(debits)
    transfers = Decimal(transfers)
    return TransactionList(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        credits=credits,
        debits=debits,
        net=credits - debits,
        transfers=transfers,
    )


async def get_transaction(
    session: AsyncSession, user_id: UUID, transaction_id: UUID
) -> TransactionRead | None:
    """Fetch one ledger row by id."""
    row = (
        await session.execute(
            _transaction_query().where(
                FinancialTransaction.id == transaction_id,
                FinancialTransaction.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        return None
    transaction, account_name, category_name, category_kind = row
    return _to_read(transaction, account_name, category_name, category_kind)


async def update_transaction(
    session: AsyncSession,
    user_id: UUID,
    transaction_id: UUID,
    payload: TransactionUpdate,
) -> TransactionRead | None:
    """Apply a manual category and/or transfer flag to a transaction."""
    transaction = (
        await session.execute(
            select(FinancialTransaction).where(
                FinancialTransaction.id == transaction_id,
                FinancialTransaction.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if transaction is None:
        return None

    fields_set = payload.model_fields_set
    explicit_transfer = payload.is_transfer if "is_transfer" in fields_set else None
    if "category_id" in fields_set:
        if payload.category_id is None:
            transaction.category_id = None
            transaction.categorisation_source = "uncategorised"
            transaction.is_transfer = explicit_transfer if explicit_transfer is not None else False
        else:
            category = await get_category(session, user_id, payload.category_id)
            if category is None:
                raise UnknownCategoryError(str(payload.category_id))
            transaction.category_id = category.id
            transaction.categorisation_source = "manual"
            category_is_transfer = category.kind == "transfer"
            transaction.is_transfer = (
                explicit_transfer if explicit_transfer is not None else category_is_transfer
            ) or category_is_transfer
    elif explicit_transfer is not None:
        transaction.is_transfer = explicit_transfer

    await session.flush()
    await session.refresh(transaction)
    return await get_transaction(session, user_id, transaction_id)


async def cash_flow(
    session: AsyncSession, user_id: UUID, period_month: date
) -> CashFlowRead:
    """Aggregate one month of non-transfer income and expenses by category."""
    start, end = month_bounds(period_month)
    rows = (
        await session.execute(
            select(
                FinancialTransaction.category_id,
                TransactionCategory.name.label("category_name"),
                TransactionCategory.kind.label("category_kind"),
                FinancialTransaction.direction,
                FinancialTransaction.amount,
                FinancialTransaction.is_transfer,
            )
            .outerjoin(
                TransactionCategory,
                TransactionCategory.id == FinancialTransaction.category_id,
            )
            .where(
                FinancialTransaction.user_id == user_id,
                FinancialTransaction.transaction_date >= start,
                FinancialTransaction.transaction_date < end,
            )
        )
    ).all()

    transfers = Decimal("0")
    income = Decimal("0")
    expenses = Decimal("0")
    grouped: dict[
        tuple[UUID | None, str, str | None], dict[str, Decimal | int]
    ] = defaultdict(lambda: {"credits": Decimal("0"), "debits": Decimal("0"), "count": 0})

    for category_id, category_name, category_kind, direction, amount, is_transfer in rows:
        value = Decimal(amount)
        # Transfers never count as income or spending; they only get reported.
        if is_transfer or category_kind == "transfer":
            transfers += value
            continue
        key = (category_id, category_name or "Uncategorised", category_kind)
        bucket = grouped[key]
        if direction == "credit":
            bucket["credits"] = cast(Decimal, bucket["credits"]) + value
        else:
            bucket["debits"] = cast(Decimal, bucket["debits"]) + value
        bucket["count"] = cast(int, bucket["count"]) + 1

    by_category: list[CashFlowCategory] = []
    for (category_id, category_name, kind), bucket in grouped.items():
        credits = cast(Decimal, bucket["credits"])
        debits = cast(Decimal, bucket["debits"])
        count = cast(int, bucket["count"])

        if kind == "income":
            net_income = credits - debits
            income += net_income
            if net_income != 0:
                by_category.append(
                    CashFlowCategory(
                        category_id=category_id,
                        category_name=category_name,
                        kind="income",
                        amount=net_income,
                        transaction_count=count,
                    )
                )
        elif kind is None:
            # Uncategorised rows fall back to their direction.
            if credits > 0:
                income += credits
                by_category.append(
                    CashFlowCategory(
                        category_id=None,
                        category_name="Uncategorised income",
                        kind="income",
                        amount=credits,
                        transaction_count=count,
                    )
                )
            if debits > 0:
                expenses += debits
                by_category.append(
                    CashFlowCategory(
                        category_id=None,
                        category_name="Uncategorised expense",
                        kind="expense",
                        amount=debits,
                        transaction_count=count,
                    )
                )
        else:
            net_spend = debits - credits
            expenses += net_spend
            if net_spend != 0:
                by_category.append(
                    CashFlowCategory(
                        category_id=category_id,
                        category_name=category_name,
                        kind="expense",
                        amount=net_spend,
                        transaction_count=count,
                    )
                )

    by_category.sort(key=lambda item: (item.kind, -item.amount))
    net = income - expenses
    savings_rate = (
        round(float((net / income) * Decimal(100)), 2) if income > 0 else 0.0
    )
    return CashFlowRead(
        period_month=start,
        income=income,
        expenses=expenses,
        net=net,
        savings_rate=savings_rate,
        transfers_excluded=transfers,
        by_category=by_category,
    )
