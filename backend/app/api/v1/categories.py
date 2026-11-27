"""Transaction category, keyword rule, and retroactive categorisation endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.db.models import TransactionCategory, User
from app.schemas.categories import (
    ApplyRulesResult,
    CategoryCreate,
    CategoryKind,
    CategoryRead,
    CategoryUpdate,
    RuleCreate,
    RuleRead,
    RuleUpdate,
)
from app.services import categorisation as categorisation_service

router = APIRouter(tags=["categorisation"])


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    kind: Annotated[CategoryKind | None, Query()] = None,
) -> list[TransactionCategory]:
    """List system categories plus the current user's categories."""
    return await categorisation_service.list_categories(
        session, current_user.id, kind=kind
    )


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> TransactionCategory:
    """Create a user-defined category."""
    try:
        return await categorisation_service.create_category(
            session, current_user.id, payload
        )
    except categorisation_service.CategoryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name and kind already exists",
        ) from exc
    except categorisation_service.UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parent category not found"
        ) from exc


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> TransactionCategory:
    """Rename or re-parent a user-defined category."""
    try:
        category = await categorisation_service.update_category(
            session, current_user.id, category_id, payload
        )
    except categorisation_service.SystemCategoryProtectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System categories cannot be modified",
        ) from exc
    except categorisation_service.CategoryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name and kind already exists",
        ) from exc
    except categorisation_service.UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parent category not found"
        ) from exc
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Delete a user-defined category (system categories are protected)."""
    try:
        deleted = await categorisation_service.delete_category(
            session, current_user.id, category_id
        )
    except categorisation_service.SystemCategoryProtectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System categories cannot be deleted",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/rules", response_model=list[RuleRead])
async def list_rules(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> list[RuleRead]:
    """List the user's keyword rules in evaluation order."""
    return await categorisation_service.list_rules(session, current_user.id)


@router.post("/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> RuleRead:
    """Create a keyword rule and re-apply rules to existing transactions."""
    try:
        return await categorisation_service.create_rule(session, current_user.id, payload)
    except categorisation_service.UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        ) from exc


@router.patch("/rules/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: UUID,
    payload: RuleUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> RuleRead:
    """Update a keyword rule and re-apply rules to existing transactions."""
    try:
        rule = await categorisation_service.update_rule(
            session, current_user.id, rule_id, payload
        )
    except categorisation_service.UnknownCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        ) from exc
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Delete a keyword rule."""
    deleted = await categorisation_service.delete_rule(session, current_user.id, rule_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/categorisation/apply", response_model=ApplyRulesResult)
async def apply_rules(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> ApplyRulesResult:
    """Re-run active rules over all non-manual transactions."""
    return await categorisation_service.apply_rules(session, current_user.id)
