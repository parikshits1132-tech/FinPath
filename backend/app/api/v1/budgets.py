"""Monthly budget CRUD endpoints with computed spend and variance."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.db.models import User
from app.schemas.transactions import BudgetCreate, BudgetRead, BudgetUpdate
from app.services import budgets as budget_service
from app.services.categorisation import UnknownCategoryError

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetRead])
async def list_budgets(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    month: Annotated[date, Query(description="First day of the month, e.g. 2026-11-01")],
) -> list[BudgetRead]:
    """List the month's budgets with spend derived from non-transfer transactions."""
    if month.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month must be the first day of a month",
        )
    return await budget_service.list_budgets(session, current_user.id, month)


@router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: BudgetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> BudgetRead:
    """Create a monthly budget for an expense category."""
    try:
        return await budget_service.create_budget(session, current_user.id, payload)
    except UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        ) from exc
    except budget_service.BudgetCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Budgets can only target expense categories",
        ) from exc
    except budget_service.BudgetConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A budget already exists for this category and month",
        ) from exc


@router.patch("/{budget_id}", response_model=BudgetRead)
async def update_budget(
    budget_id: UUID,
    payload: BudgetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> BudgetRead:
    """Update a budget limit."""
    budget = await budget_service.update_budget(
        session, current_user.id, budget_id, payload
    )
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Delete a budget."""
    deleted = await budget_service.delete_budget(session, current_user.id, budget_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
