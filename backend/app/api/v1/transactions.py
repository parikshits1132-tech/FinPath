"""Transaction browsing, manual categorisation, and cash-flow endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.db.models import User
from app.schemas.transactions import (
    CashFlowRead,
    Direction,
    TransactionList,
    TransactionRead,
    TransactionUpdate,
)
from app.services import transactions as transaction_service
from app.services.categorisation import UnknownCategoryError

cashflow_router = APIRouter(tags=["cash-flow"])
transactions_router = APIRouter(prefix="/transactions", tags=["transactions"])


@cashflow_router.get("/cash-flow", response_model=CashFlowRead)
async def get_cash_flow(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    month: Annotated[date, Query(description="First day of the month, e.g. 2026-11-01")],
) -> CashFlowRead:
    """Monthly income and expenses with transfers excluded."""
    if month.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month must be the first day of a month",
        )
    return await transaction_service.cash_flow(session, current_user.id, month)


@transactions_router.get("", response_model=TransactionList)
async def list_transactions(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    account_id: Annotated[UUID | None, Query()] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    direction: Annotated[Direction | None, Query()] = None,
    is_transfer: Annotated[bool | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionList:
    """List transactions with filters, pagination, and transfer-aware totals."""
    return await transaction_service.list_transactions(
        session,
        current_user.id,
        account_id=account_id,
        category_id=category_id,
        direction=direction,
        is_transfer=is_transfer,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )


@transactions_router.get("/{transaction_id}", response_model=TransactionRead)
async def get_transaction(
    transaction_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> TransactionRead:
    """Fetch one transaction."""
    transaction = await transaction_service.get_transaction(
        session, current_user.id, transaction_id
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    return transaction


@transactions_router.patch("/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: UUID,
    payload: TransactionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> TransactionRead:
    """Manually categorise a transaction and/or override the transfer flag."""
    try:
        transaction = await transaction_service.update_transaction(
            session, current_user.id, transaction_id, payload
        )
    except UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        ) from exc
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    return transaction
