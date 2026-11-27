"""Integration tests for account CRUD, derived balances, and safe deletion."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.db.models import FinancialTransaction
from app.db.session import get_session_factory, set_rls_user_id
from tests.conftest import register_and_login


async def _create_account(
    client: AsyncClient, headers: dict[str, str], *, name: str = "HDFC Savings"
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "name": name,
            "account_type": "savings",
            "institution_name": "HDFC Bank",
            "masked_account_number": "XXXX1234",
            "opening_balance": "10000.0000",
            "opening_balance_date": "2026-04-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_transaction(
    user_id: UUID, account_id: UUID, *, direction: str, amount: str, fingerprint: str
) -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_rls_user_id(session, user_id)
        session.add(
            FinancialTransaction(
                user_id=user_id,
                account_id=account_id,
                transaction_date=date(2026, 4, 5),
                direction=direction,
                amount=Decimal(amount),
                description_raw=f"{direction.upper()} TEST",
                description_clean=f"{direction.upper()} TEST",
                fingerprint=fingerprint,
            )
        )


async def test_account_crud_and_derived_balance(client: AsyncClient) -> None:
    """Opening balance plus credits and debits drives the returned balance."""
    user_id, headers = await register_and_login(client, "accounts@example.com")
    created = await _create_account(client, headers)

    assert created["opening_balance"] == "10000.0000"
    assert created["derived_balance"] == "10000.0000"
    assert created["transaction_count"] == 0
    assert created["currency"] == "INR"

    account_id = UUID(str(created["id"]))
    await _add_transaction(
        user_id, account_id, direction="credit", amount="2500.50", fingerprint="a" * 64
    )
    await _add_transaction(
        user_id, account_id, direction="debit", amount="500.25", fingerprint="b" * 64
    )

    fetched = await client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["derived_balance"] == "12000.2500"
    assert fetched.json()["transaction_count"] == 2

    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(account_id)]

    patched = await client.patch(
        f"/api/v1/accounts/{account_id}",
        headers=headers,
        json={"opening_balance": "20000.0000", "name": "HDFC Primary Savings"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "HDFC Primary Savings"
    assert patched.json()["derived_balance"] == "22000.2500"


async def test_duplicate_active_account_is_rejected(client: AsyncClient) -> None:
    """The active-account unique index surfaces as 409 rather than a 500."""
    _, headers = await register_and_login(client, "duplicates@example.com")
    await _create_account(client, headers, name="Same Name")
    duplicate = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "name": "same name",
            "account_type": "savings",
            "institution_name": "HDFC Bank",
            "opening_balance": "0",
            "opening_balance_date": "2026-04-01",
        },
    )
    assert duplicate.status_code == 409


async def test_safe_delete_requires_confirmation_then_cascades(client: AsyncClient) -> None:
    """Accounts with transactions are protected unless deletion is explicitly confirmed."""
    user_id, headers = await register_and_login(client, "delete@example.com")
    created = await _create_account(client, headers)
    account_id = UUID(str(created["id"]))
    await _add_transaction(
        user_id, account_id, direction="debit", amount="99.00", fingerprint="c" * 64
    )

    blocked = await client.delete(f"/api/v1/accounts/{account_id}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["transaction_count"] == 1

    deleted = await client.delete(
        f"/api/v1/accounts/{account_id}?confirm_delete_transactions=true", headers=headers
    )
    assert deleted.status_code == 204

    settings = get_settings()
    engine = create_engine(settings.migration_database_url)
    try:
        with engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT COUNT(*) FROM financial_transactions WHERE account_id = :id"),
                {"id": str(account_id)},
            ).scalar_one()
    finally:
        engine.dispose()
    assert remaining == 0

    missing = await client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert missing.status_code == 404


async def test_accounts_are_isolated_between_users(client: AsyncClient) -> None:
    """User B cannot see, update, or delete User A's account."""
    _, headers_a = await register_and_login(client, "owner@example.com")
    _, headers_b = await register_and_login(client, "intruder@example.com")
    created = await _create_account(client, headers_a)
    account_id = created["id"]

    assert (await client.get("/api/v1/accounts", headers=headers_b)).json() == []
    assert (
        await client.get(f"/api/v1/accounts/{account_id}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/accounts/{account_id}",
            headers=headers_b,
            json={"name": "Hacked"},
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/accounts/{account_id}", headers=headers_b)
    ).status_code == 404


async def test_archived_account_hidden_when_requested(client: AsyncClient) -> None:
    """Archiving keeps the row but can hide it from active lists."""
    _, headers = await register_and_login(client, "archive@example.com")
    created = await _create_account(client, headers)
    account_id = created["id"]

    archived = await client.patch(
        f"/api/v1/accounts/{account_id}", headers=headers, json={"is_active": False}
    )
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False

    active_only = await client.get("/api/v1/accounts?include_inactive=false", headers=headers)
    assert active_only.json() == []
    everything = await client.get("/api/v1/accounts", headers=headers)
    assert len(everything.json()) == 1
