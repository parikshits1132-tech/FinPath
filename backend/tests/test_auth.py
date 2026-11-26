"""Tests for authentication, pwdlib Argon2 hashing, PII-safe logging, and user lifecycle."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.logging import sanitize_log_context
from app.core.security import hash_password, verify_password
from app.db.models import FinancialAccount
from app.db.session import get_session_factory, set_rls_user_id
from tests.conftest import register_and_login


def test_pwdlib_argon2_hashing() -> None:
    """Passwords use Argon2id via pwdlib and verify accurately."""
    hashed = hash_password("FinPath@1234")
    assert hashed.startswith("$argon2")
    assert verify_password("FinPath@1234", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_pii_log_redaction() -> None:
    """Sensitive fields are masked before logging."""
    clean = sanitize_log_context(
        {
            "user_id": "abc",
            "email": "user@example.com",
            "password": "secret",
            "token": "jwt.token.here",
        }
    )
    assert clean["user_id"] == "abc"
    assert clean["email"] == "[REDACTED]"
    assert clean["password"] == "[REDACTED]"
    assert clean["token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Health check confirms API and DB connectivity."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_register_duplicate_login_refresh_and_me(client: AsyncClient) -> None:
    """Full auth lifecycle works and enforces duplicate/invalid credentials."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "Alice@example.com",
            "password": "Password#123",
            "full_name": "Alice Sharma",
        },
    )
    assert reg.status_code == 201
    body = reg.json()
    assert body["email"] == "alice@example.com"
    assert body["base_currency"] == "INR"

    dup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "Password#123",
            "full_name": "Alice Duplicate",
        },
    )
    assert dup.status_code == 409

    bad_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "Password#123"},
    )
    assert login.status_code == 200
    tokens = login.json()

    # Access token cannot be used on refresh endpoint
    bad_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )
    assert bad_refresh.status_code == 401

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    new_access = refreshed.json()["access_token"]

    unauth_me = await client.get("/api/v1/me")
    assert unauth_me.status_code == 401

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "Alice Sharma"

    updated = await client.patch(
        "/api/v1/me",
        json={"full_name": "Alice S."},
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Alice S."


@pytest.mark.asyncio
async def test_delete_me_cascades_owned_records_under_rls(client: AsyncClient) -> None:
    """Deleting a user cascades cleanly to RLS-protected child tables."""
    user_id, headers = await register_and_login(client, "cascade@example.com")

    # Insert a child financial_account for this user under RLS
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_rls_user_id(session, user_id)
        session.add(
            FinancialAccount(
                user_id=user_id,
                name="Primary Savings",
                account_type="savings",
                opening_balance=Decimal("10000.0000"),
                opening_balance_date=date(2026, 1, 1),
            )
        )

    deleted = await client.delete("/api/v1/me", headers=headers)
    assert deleted.status_code == 204

    me_after = await client.get("/api/v1/me", headers=headers)
    assert me_after.status_code == 401

    settings = get_settings()
    sync_engine = create_engine(settings.migration_database_url)
    try:
        with sync_engine.connect() as conn:
            acct_count = conn.execute(
                text("SELECT COUNT(*) FROM financial_accounts WHERE user_id = :uid"),
                {"uid": str(UUID(str(user_id)))},
            ).scalar_one()
            assert acct_count == 0
    finally:
        sync_engine.dispose()
