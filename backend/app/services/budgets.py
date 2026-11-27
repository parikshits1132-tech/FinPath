"""Monthly budget CRUD with Decimal spend and variance calculations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from finpath_core.cashflow import budget_variance, month_bounds
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Budget, FinancialTransaction, TransactionCategory
from app.schemas.transactions import BudgetCreate, BudgetRead, BudgetUpdate
from app.services.categorisation import UnknownCategoryError, get_category


class BudgetConflictError(Exception):
    """Raised when a budget already exists for the category and month."""


class BudgetCategoryError(Exception):
    """Raised when a budget targets a non-expense category."""


def _to_read(
    budget: Budget, category: TransactionCategory, spent: Decimal
) -> BudgetRead:
    variance = budget_variance(Decimal(budget.limit_amount), spent)
    return BudgetRead(
        id=budget.id,
        category_id=budget.category_id,
        category_name=category.name,
        period_month=budget.period_month,
        limit_amount=variance.limit_amount,
        spent_amount=variance.spent_amount,
        remaining_amount=variance.remaining_amount,
        variance_amount=variance.variance_amount,
        percent_used=variance.percent_used,
        is_over_budget=variance.is_over_budget,
        currency=budget.currency,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


async def _spent_by_category(
    session: AsyncSession, user_id: UUID, period_month: date
) -> dict[UUID, Decimal]:
    """Return net spend per category for one month, excluding transfers."""
    start, end = month_bounds(period_month)
    spend = func.coalesce(
        func.sum(
            case(
                (FinancialTransaction.direction == "debit", FinancialTransaction.amount),
                else_=-FinancialTransaction.amount,
            )
        ),
        Decimal("0"),
    )
    rows = (
        await session.execute(
            select(FinancialTransaction.category_id, spend)
            .where(
                FinancialTransaction.user_id == user_id,
                FinancialTransaction.transaction_date >= start,
                FinancialTransaction.transaction_date < end,
                FinancialTransaction.is_transfer.is_(False),
                FinancialTransaction.category_id.is_not(None),
            )
            .group_by(FinancialTransaction.category_id)
        )
    ).all()
    return {
        category_id: Decimal(total)
        for category_id, total in rows
        if category_id is not None
    }


async def list_budgets(
    session: AsyncSession, user_id: UUID, period_month: date
) -> list[BudgetRead]:
    """Return the month's budgets with spend computed from the ledger."""
    rows = (
        await session.execute(
            select(Budget, TransactionCategory)
            .join(TransactionCategory, TransactionCategory.id == Budget.category_id)
            .where(
                Budget.user_id == user_id,
                Budget.period_month == period_month,
            )
            .order_by(TransactionCategory.name)
        )
    ).all()
    spent = await _spent_by_category(session, user_id, period_month)
    return [
        _to_read(budget, category, spent.get(budget.category_id, Decimal("0")))
        for budget, category in rows
    ]


async def get_budget(
    session: AsyncSession, user_id: UUID, budget_id: UUID
) -> BudgetRead | None:
    """Fetch one budget with computed spend."""
    row = (
        await session.execute(
            select(Budget, TransactionCategory)
            .join(TransactionCategory, TransactionCategory.id == Budget.category_id)
            .where(Budget.id == budget_id, Budget.user_id == user_id)
        )
    ).first()
    if row is None:
        return None
    budget, category = row
    spent = await _spent_by_category(session, user_id, budget.period_month)
    return _to_read(budget, category, spent.get(budget.category_id, Decimal("0")))


async def create_budget(
    session: AsyncSession, user_id: UUID, payload: BudgetCreate
) -> BudgetRead:
    """Create a budget for an expense category and month."""
    category = await get_category(session, user_id, payload.category_id)
    if category is None:
        raise UnknownCategoryError(str(payload.category_id))
    if category.kind != "expense":
        raise BudgetCategoryError(category.kind)
    budget = Budget(
        user_id=user_id,
        category_id=category.id,
        period_month=payload.period_month,
        limit_amount=payload.limit_amount,
    )
    session.add(budget)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise BudgetConflictError from exc
    await session.refresh(budget)
    spent = await _spent_by_category(session, user_id, budget.period_month)
    return _to_read(budget, category, spent.get(budget.category_id, Decimal("0")))


async def update_budget(
    session: AsyncSession, user_id: UUID, budget_id: UUID, payload: BudgetUpdate
) -> BudgetRead | None:
    """Update the limit of an existing budget."""
    row = (
        await session.execute(
            select(Budget, TransactionCategory)
            .join(TransactionCategory, TransactionCategory.id == Budget.category_id)
            .where(Budget.id == budget_id, Budget.user_id == user_id)
        )
    ).first()
    if row is None:
        return None
    budget, category = row
    budget.limit_amount = payload.limit_amount
    await session.flush()
    await session.refresh(budget)
    spent = await _spent_by_category(session, user_id, budget.period_month)
    return _to_read(budget, category, spent.get(budget.category_id, Decimal("0")))


async def delete_budget(session: AsyncSession, user_id: UUID, budget_id: UUID) -> bool:
    """Delete a budget owned by the current user."""
    budget = (
        await session.execute(
            select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
        )
    ).scalar_one_or_none()
    if budget is None:
        return False
    await session.delete(budget)
    await session.flush()
    return True
