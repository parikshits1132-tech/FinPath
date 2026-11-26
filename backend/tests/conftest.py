"""Pytest fixtures for FinPath backend and PostgreSQL RLS tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory, set_rls_user_id
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Ensure Alembic migrations are applied to head before running tests."""
    os.environ.setdefault("ENV", "test")
    get_settings.cache_clear()
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def reset_test_data() -> AsyncIterator[None]:
    """Dispose async engine pool and clean test users after each test."""
    yield
    await get_engine().dispose()
    settings = get_settings()
    sync_engine = create_engine(settings.migration_database_url)
    try:
        with sync_engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE email LIKE '%@example.com'"))
            conn.execute(text("DELETE FROM transaction_categories WHERE is_system = false"))
    finally:
        sync_engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def register_and_login(
    client: AsyncClient, email: str, password: str = "StrongPass#2026", full_name: str = "Test User"
) -> tuple[UUID, dict[str, str]]:
    """Helper to register a user and return (user_id, auth_headers)."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert reg.status_code == 201, reg.text
    user_id = UUID(reg.json()["id"])

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    return user_id, {"Authorization": f"Bearer {access_token}"}


async def open_rls_session(user_id: UUID | None) -> AsyncIterator[AsyncSession]:
    """Yield a finpath_app session optionally scoped to user_id."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        if user_id is not None:
            await set_rls_user_id(session, user_id)
        yield session
