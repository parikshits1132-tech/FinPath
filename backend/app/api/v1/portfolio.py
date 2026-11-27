"""Non-market asset and term-liability CRUD endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.db.models import Asset, Liability, User
from app.schemas.portfolio import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    LiabilityCreate,
    LiabilityRead,
    LiabilityUpdate,
)
from app.services import portfolio as portfolio_service

assets_router = APIRouter(prefix="/assets", tags=["assets"])
liabilities_router = APIRouter(prefix="/liabilities", tags=["liabilities"])


@assets_router.get("", response_model=list[AssetRead])
async def list_assets(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> list[Asset]:
    """List the user's non-market assets."""
    return await portfolio_service.list_assets(session, current_user.id)


@assets_router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Asset:
    """Create a non-market asset."""
    return await portfolio_service.create_asset(session, current_user.id, payload)


@assets_router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Asset:
    """Update a non-market asset."""
    asset = await portfolio_service.update_asset(
        session, current_user.id, asset_id, payload
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@assets_router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Delete a non-market asset."""
    deleted = await portfolio_service.delete_asset(session, current_user.id, asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@liabilities_router.get("", response_model=list[LiabilityRead])
async def list_liabilities(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> list[Liability]:
    """List the user's term liabilities (credit cards are accounts, not liabilities)."""
    return await portfolio_service.list_liabilities(session, current_user.id)


@liabilities_router.post(
    "", response_model=LiabilityRead, status_code=status.HTTP_201_CREATED
)
async def create_liability(
    payload: LiabilityCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Liability:
    """Create a term liability."""
    try:
        return await portfolio_service.create_liability(
            session, current_user.id, payload
        )
    except portfolio_service.UnknownSecuredAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Secured asset not found"
        ) from exc


@liabilities_router.patch("/{liability_id}", response_model=LiabilityRead)
async def update_liability(
    liability_id: UUID,
    payload: LiabilityUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Liability:
    """Update a term liability."""
    try:
        liability = await portfolio_service.update_liability(
            session, current_user.id, liability_id, payload
        )
    except portfolio_service.UnknownSecuredAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Secured asset not found"
        ) from exc
    if liability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Liability not found"
        )
    return liability


@liabilities_router.delete("/{liability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_liability(
    liability_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Delete a term liability."""
    deleted = await portfolio_service.delete_liability(
        session, current_user.id, liability_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Liability not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
