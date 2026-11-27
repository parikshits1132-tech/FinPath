"""Non-market asset and term-liability CRUD services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Liability
from app.schemas.portfolio import AssetCreate, AssetUpdate, LiabilityCreate, LiabilityUpdate


class UnknownSecuredAssetError(Exception):
    """Raised when a liability references an asset the user does not own."""


async def _get_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(Asset.id == asset_id, Asset.user_id == user_id)
        )
    ).scalar_one_or_none()


async def list_assets(session: AsyncSession, user_id: UUID) -> list[Asset]:
    """Return the user's assets, largest valuation first."""
    stmt = (
        select(Asset)
        .where(Asset.user_id == user_id)
        .order_by(Asset.current_value.desc(), Asset.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_asset(
    session: AsyncSession, user_id: UUID, payload: AssetCreate
) -> Asset:
    """Create a non-market asset valuation."""
    asset = Asset(
        user_id=user_id,
        name=payload.name.strip(),
        asset_class=payload.asset_class,
        current_value=payload.current_value,
        valuation_date=payload.valuation_date,
        notes=(payload.notes or "").strip() or None,
    )
    session.add(asset)
    await session.flush()
    await session.refresh(asset)
    return asset


async def update_asset(
    session: AsyncSession, user_id: UUID, asset_id: UUID, payload: AssetUpdate
) -> Asset | None:
    """Apply a partial update to an asset."""
    asset = await _get_asset(session, user_id, asset_id)
    if asset is None:
        return None
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = str(changes["name"]).strip()
    if "notes" in changes:
        raw_notes = changes["notes"]
        changes["notes"] = str(raw_notes).strip() if raw_notes else None
    for field_name, value in changes.items():
        setattr(asset, field_name, value)
    await session.flush()
    await session.refresh(asset)
    return asset


async def delete_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> bool:
    """Delete an asset; linked liabilities keep their row and null the link."""
    asset = await _get_asset(session, user_id, asset_id)
    if asset is None:
        return False
    await session.delete(asset)
    await session.flush()
    return True


async def list_liabilities(session: AsyncSession, user_id: UUID) -> list[Liability]:
    """Return term liabilities, largest outstanding principal first."""
    stmt = (
        select(Liability)
        .where(Liability.user_id == user_id)
        .order_by(Liability.principal_outstanding.desc(), Liability.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_liability(
    session: AsyncSession, user_id: UUID, payload: LiabilityCreate
) -> Liability:
    """Create a term liability, validating any secured-asset link."""
    if payload.secured_asset_id is not None:
        asset = await _get_asset(session, user_id, payload.secured_asset_id)
        if asset is None:
            raise UnknownSecuredAssetError(str(payload.secured_asset_id))
    liability = Liability(
        user_id=user_id,
        name=payload.name.strip(),
        liability_type=payload.liability_type,
        principal_outstanding=payload.principal_outstanding,
        interest_rate_annual=payload.interest_rate_annual,
        emi_amount=payload.emi_amount,
        as_of_date=payload.as_of_date,
        secured_asset_id=payload.secured_asset_id,
    )
    session.add(liability)
    await session.flush()
    await session.refresh(liability)
    return liability


async def update_liability(
    session: AsyncSession, user_id: UUID, liability_id: UUID, payload: LiabilityUpdate
) -> Liability | None:
    """Apply a partial update to a liability."""
    liability = (
        await session.execute(
            select(Liability).where(
                Liability.id == liability_id,
                Liability.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if liability is None:
        return None

    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = str(changes["name"]).strip()
    if "secured_asset_id" in changes and changes["secured_asset_id"] is not None:
        asset = await _get_asset(session, user_id, changes["secured_asset_id"])
        if asset is None:
            raise UnknownSecuredAssetError(str(changes["secured_asset_id"]))
    for field_name, value in changes.items():
        setattr(liability, field_name, value)
    await session.flush()
    await session.refresh(liability)
    return liability


async def delete_liability(
    session: AsyncSession, user_id: UUID, liability_id: UUID
) -> bool:
    """Delete a term liability."""
    liability = (
        await session.execute(
            select(Liability).where(
                Liability.id == liability_id,
                Liability.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if liability is None:
        return False
    await session.delete(liability)
    await session.flush()
    return True
