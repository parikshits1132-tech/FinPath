"""Financial account CRUD endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.db.models import User
from app.schemas.accounts import AccountCreate, AccountRead, AccountUpdate
from app.services import accounts as account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    include_inactive: Annotated[bool, Query()] = True,
) -> list[AccountRead]:
    """List the current user's accounts with balances derived from transactions."""
    return await account_service.list_accounts(
        session, current_user.id, include_inactive=include_inactive
    )


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> AccountRead:
    """Create a financial account."""
    try:
        return await account_service.create_account(session, current_user.id, payload)
    except account_service.DuplicateAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active account with the same name and institution already exists",
        ) from exc


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> AccountRead:
    """Fetch a single account by id."""
    account = await account_service.get_account(session, current_user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> AccountRead:
    """Partially update an account."""
    try:
        account = await account_service.update_account(
            session, current_user.id, account_id, payload
        )
    except account_service.DuplicateAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active account with the same name and institution already exists",
        ) from exc
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    confirm_delete_transactions: Annotated[bool, Query()] = False,
) -> Response:
    """Delete an account, refusing to discard transactions without explicit confirmation."""
    try:
        deleted = await account_service.delete_account(
            session,
            current_user.id,
            account_id,
            confirm_delete_transactions=confirm_delete_transactions,
        )
    except account_service.AccountHasTransactionsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Account has transactions. Archive it with PATCH is_active=false "
                    "or pass confirm_delete_transactions=true to delete everything."
                ),
                "transaction_count": exc.transaction_count,
            },
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
