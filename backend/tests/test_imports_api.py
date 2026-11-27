"""Integration tests for CSV imports, deduplication, archival, and error resolution."""

from __future__ import annotations

import hashlib
import io
from uuid import UUID

import pyarrow.parquet as pq
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.db.models import FinancialTransaction
from app.db.session import get_session_factory, set_rls_user_id
from app.services.storage import get_memory_storage
from tests.conftest import register_and_login

SAMPLE_CSV = (
    "Date,Description,Debit,Credit,Reference\n"
    "01/04/2026,SWIGGY ORDER,450.50,,TXN1\n"
    "02/04/2026,SALARY CREDIT,,120000.00,SAL1\n"
    "31/02/2026,BAD DATE ROW,100,,TXN2\n"
    "04/04/2026,NO AMOUNT ROW,,,TXN3\n"
    "05/04/2026,AMAZON PURCHASE,2999.00,,TXN4\n"
)


async def _create_account(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    opening: str = "10000.0000",
    name: str = "HDFC Savings",
) -> UUID:
    response = await client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "name": name,
            "account_type": "savings",
            "institution_name": "HDFC Bank",
            "opening_balance": opening,
            "opening_balance_date": "2026-04-01",
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    account_id: UUID,
    content: str,
    *,
    filename: str = "statement.csv",
    parser_name: str = "bank_csv",
) -> Response:
    return await client.post(
        "/api/v1/imports",
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
        data={"account_id": str(account_id), "parser_name": parser_name},
    )


async def _transaction_fingerprints(user_id: UUID) -> list[str]:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_rls_user_id(session, user_id)
        rows = (
            await session.execute(select(FinancialTransaction.fingerprint))
        ).scalars()
        return list(rows)


async def test_import_parses_archives_and_resolves_errors(client: AsyncClient) -> None:
    """A mixed file inserts valid rows, stores raw+Parquet, and resolves errors."""
    user_id, headers = await register_and_login(client, "importer@example.com")
    account_id = await _create_account(client, headers)

    response = await _upload(client, headers, account_id, SAMPLE_CSV)
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["status"] == "partial_failed"
    assert batch["total_rows"] == 5
    assert batch["inserted_rows"] == 3
    assert batch["duplicate_rows"] == 0
    assert batch["error_rows"] == 2
    assert batch["parsed_parquet_key"].startswith(f"parsed/{user_id}/")
    assert batch["file_sha256"] == hashlib.sha256(SAMPLE_CSV.encode("utf-8")).hexdigest()

    # Raw CSV and parsed Parquet are both archived per batch.
    storage = get_memory_storage()
    all_keys = storage.keys()
    raw_keys = [key for key in all_keys if key.startswith(f"raw/{user_id}/")]
    parquet_keys = [key for key in all_keys if key.endswith("rows.parquet")]
    assert raw_keys == [batch["raw_object_key"]]
    assert parquet_keys == [batch["parsed_parquet_key"]]
    assert storage.get_object(batch["raw_object_key"]) == SAMPLE_CSV.encode("utf-8")
    parquet_blob = storage.get_object(batch["parsed_parquet_key"])
    assert parquet_blob.startswith(b"PAR1")
    table = pq.read_table(io.BytesIO(parquet_blob))
    assert table.num_rows == 3
    assert set(table.column_names) >= {
        "fingerprint",
        "occurrence_index",
        "is_duplicate",
        "description_clean",
    }

    account = await client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account.json()["transaction_count"] == 3
    assert account.json()["derived_balance"] == "126550.5000"

    errors_response = await client.get(
        f"/api/v1/imports/{batch['id']}/errors", headers=headers
    )
    assert errors_response.status_code == 200
    errors = errors_response.json()
    assert [error["error_code"] for error in errors] == ["INVALID_DATE", "MISSING_AMOUNT"]
    assert [error["resolution_status"] for error in errors] == ["open", "open"]

    corrected = await client.post(
        f"/api/v1/imports/{batch['id']}/errors/{errors[0]['id']}/resolve",
        headers=headers,
        json={
            "resolution": "corrected",
            "corrected_payload": {
                "transaction_date": "2026-04-03",
                "direction": "debit",
                "amount": "700.00",
                "description_raw": "CORRECTED DATE ROW",
                "reference_number": "FIX1",
            },
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["resolution_status"] == "corrected"
    assert corrected.json()["corrected_payload"]["amount"] == "700.00"

    ignored = await client.post(
        f"/api/v1/imports/{batch['id']}/errors/{errors[1]['id']}/resolve",
        headers=headers,
        json={"resolution": "ignored"},
    )
    assert ignored.status_code == 200
    assert ignored.json()["resolution_status"] == "ignored"

    refreshed = await client.get(f"/api/v1/imports/{batch['id']}", headers=headers)
    assert refreshed.json()["status"] == "completed"
    assert refreshed.json()["inserted_rows"] == 4

    account = await client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account.json()["transaction_count"] == 4
    assert account.json()["derived_balance"] == "125850.5000"

    double_resolve = await client.post(
        f"/api/v1/imports/{batch['id']}/errors/{errors[1]['id']}/resolve",
        headers=headers,
        json={"resolution": "ignored"},
    )
    assert double_resolve.status_code == 409


async def test_reimport_produces_identical_fingerprints_and_skips_rows(
    client: AsyncClient,
) -> None:
    """Re-importing the same file inserts zero rows and reports duplicates."""
    user_id, headers = await register_and_login(client, "reimport@example.com")
    account_id = await _create_account(client, headers)

    first = (await _upload(client, headers, account_id, SAMPLE_CSV)).json()
    second = (await _upload(client, headers, account_id, SAMPLE_CSV)).json()

    assert first["inserted_rows"] == 3
    assert second["inserted_rows"] == 0
    assert second["duplicate_rows"] == 3
    assert second["error_rows"] == 2
    assert second["status"] == "partial_failed"
    assert first["file_sha256"] == second["file_sha256"]
    assert len(await _transaction_fingerprints(user_id)) == 3


async def test_identical_same_day_rows_are_kept_then_deduplicated(
    client: AsyncClient,
) -> None:
    """Two identical INR 200 rows on one day get indices 0/1; both re-import as dupes."""
    user_id, headers = await register_and_login(client, "same-day@example.com")
    account_id = await _create_account(client, headers)
    csv_text = (
        "Date,Description,Debit,Credit\n"
        "01/04/2026,UPI CHAI POINT,200.00,\n"
        "01/04/2026,UPI CHAI POINT,200.00,\n"
    )

    first = (await _upload(client, headers, account_id, csv_text)).json()
    assert first["inserted_rows"] == 2
    assert first["duplicate_rows"] == 0

    fingerprints = await _transaction_fingerprints(user_id)
    assert len(set(fingerprints)) == 2

    second = (await _upload(client, headers, account_id, csv_text)).json()
    assert second["inserted_rows"] == 0
    assert second["duplicate_rows"] == 2

    storage = get_memory_storage()
    table = pq.read_table(io.BytesIO(storage.get_object(second["parsed_parquet_key"])))
    assert table.column("occurrence_index").to_pylist() == [0, 1]
    assert table.column("is_duplicate").to_pylist() == [True, True]

    account = await client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account.json()["transaction_count"] == 2
    assert account.json()["derived_balance"] == "9600.0000"


async def test_unsupported_csv_marks_batch_failed(client: AsyncClient) -> None:
    """A structurally invalid CSV is archived but marked failed with a summary."""
    _, headers = await register_and_login(client, "badcsv@example.com")
    account_id = await _create_account(client, headers)

    response = await _upload(client, headers, account_id, "Foo,Bar\n1,2\n")
    assert response.status_code == 201
    batch = response.json()
    assert batch["status"] == "failed"
    assert batch["error_summary"]["parse_error"]
    assert batch["parsed_parquet_key"] is None

    storage = get_memory_storage()
    assert storage.exists(batch["raw_object_key"])


async def test_unknown_parser_and_inactive_account_are_rejected(
    client: AsyncClient,
) -> None:
    """Unsupported parser names and archived accounts return 400/409."""
    _, headers = await register_and_login(client, "guards@example.com")
    account_id = await _create_account(client, headers)

    unknown = await _upload(client, headers, account_id, SAMPLE_CSV, parser_name="excel_magic")
    assert unknown.status_code == 400

    archived = await client.patch(
        f"/api/v1/accounts/{account_id}", headers=headers, json={"is_active": False}
    )
    assert archived.status_code == 200
    inactive = await _upload(client, headers, account_id, SAMPLE_CSV)
    assert inactive.status_code == 409


async def test_imports_and_errors_are_isolated_between_users(client: AsyncClient) -> None:
    """User B cannot inspect or resolve User A's imports."""
    _, headers_a = await register_and_login(client, "data-owner@example.com")
    _, headers_b = await register_and_login(client, "data-intruder@example.com")
    account_id = await _create_account(client, headers_a)
    batch = (await _upload(client, headers_a, account_id, SAMPLE_CSV)).json()
    errors = (
        await client.get(f"/api/v1/imports/{batch['id']}/errors", headers=headers_a)
    ).json()

    assert (await client.get("/api/v1/imports", headers=headers_b)).json() == []
    assert (
        await client.get(f"/api/v1/imports/{batch['id']}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/imports/{batch['id']}/errors", headers=headers_b)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/imports/{batch['id']}/errors/{errors[0]['id']}/resolve",
            headers=headers_b,
            json={"resolution": "ignored"},
        )
    ).status_code == 404
    assert (
        await _upload(client, headers_b, account_id, SAMPLE_CSV)
    ).status_code == 404


async def test_import_list_filters_by_account(client: AsyncClient) -> None:
    """Batch listing supports account filters."""
    _, headers = await register_and_login(client, "listimports@example.com")
    account_a = await _create_account(client, headers, name="Account A")
    account_b = await _create_account(client, headers, name="Account B")

    batch_a = (await _upload(client, headers, account_a, SAMPLE_CSV)).json()
    batch_b1 = (await _upload(client, headers, account_b, SAMPLE_CSV)).json()
    batch_b2 = (await _upload(client, headers, account_b, SAMPLE_CSV)).json()

    all_batches = (await client.get("/api/v1/imports", headers=headers)).json()
    assert len(all_batches) == 3

    filtered = (
        await client.get(f"/api/v1/imports?account_id={account_b}", headers=headers)
    ).json()
    assert {item["id"] for item in filtered} == {batch_b1["id"], batch_b2["id"]}
    assert batch_a["id"] not in {item["id"] for item in filtered}

    limited = (await client.get("/api/v1/imports?limit=1", headers=headers)).json()
    assert len(limited) == 1
