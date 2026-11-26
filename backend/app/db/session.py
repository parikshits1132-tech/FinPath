"""Async SQLAlchemy engine, session factory, and PostgreSQL RLS context helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create and cache the async SQLAlchemy engine."""
    settings = get_settings()
    if settings.env == "test":
        return create_async_engine(settings.database_url, poolclass=NullPool)
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create and cache the async session maker."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def set_rls_user_id(session: AsyncSession, user_id: UUID) -> None:
    """Set transaction-local app.current_user_id for PostgreSQL Row-Level Security."""
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a transaction-scoped session (without RLS user context, e.g., auth endpoints)."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        yield session
