"""Statement import orchestration: parse, deduplicate, archive, and resolve errors."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from finpath_core.fingerprint import (
    clean_description,
    compute_fingerprint,
    fingerprint_occurrence_key,
)
from finpath_core.ingestion import (
    ParseResult,
    UnsupportedStatementError,
    parse_bank_csv,
)
from finpath_core.parquet import records_to_parquet_bytes
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FinancialAccount,
    FinancialTransaction,
    ImportBatch,
    ImportRowError,
)
from app.services.storage import ObjectStorage

PARSER_REGISTRY: dict[str, Any] = {
    "bank_csv": parse_bank_csv,
    "indian_bank_csv": parse_bank_csv,
}


class InactiveAccountError(Exception):
    """Raised when a statement targets an archived account."""


class UnknownParserError(Exception):
    """Raised when an import references an unknown parser."""


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sanitize_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe object-key segment."""
    candidate = Path(name or "statement.csv").name
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
    return (candidate or "statement.csv")[:200]


def _chunks(values: list[str], size: int = 5_000) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


async def _existing_fingerprints(
    session: AsyncSession, user_id: UUID, fingerprints: list[str]
) -> set[str]:
    found: set[str] = set()
    for chunk in _chunks(fingerprints):
        rows = (
            await session.execute(
                select(FinancialTransaction.fingerprint).where(
                    FinancialTransaction.user_id == user_id,
                    FinancialTransaction.fingerprint.in_(chunk),
                )
            )
        ).scalars()
        found.update(rows)
    return found


def _build_rows(
    parsed: ParseResult,
    *,
    user_id: UUID,
    account_id: UUID,
) -> list[dict[str, Any]]:
    """Assign within-file occurrence indices and fingerprints to parsed rows."""
    occurrence_counter: Counter[tuple[str, str, str, str, str, str]] = Counter()
    rows: list[dict[str, Any]] = []
    for transaction in parsed.transactions:
        key = fingerprint_occurrence_key(
            transaction_date=transaction.transaction_date,
            amount=transaction.amount,
            direction=transaction.direction,
            description_clean=transaction.description_clean,
            reference_number=transaction.reference_number,
        )
        occurrence_index = occurrence_counter[key]
        occurrence_counter[key] += 1
        fingerprint = compute_fingerprint(
            user_id=str(user_id),
            account_id=str(account_id),
            transaction_date=transaction.transaction_date,
            amount=transaction.amount,
            direction=transaction.direction,
            description_clean=transaction.description_clean,
            reference_number=transaction.reference_number,
            occurrence_index=occurrence_index,
        )
        rows.append(
            {
                "row_number": transaction.row_number,
                "transaction_date": transaction.transaction_date.isoformat(),
                "direction": transaction.direction,
                "amount": format(transaction.amount, "f"),
                "currency": "INR",
                "description_raw": transaction.description_raw,
                "description_clean": transaction.description_clean,
                "reference_number": transaction.reference_number or "",
                "occurrence_index": occurrence_index,
                "fingerprint": fingerprint,
                "is_duplicate": False,
            }
        )
    return rows


async def process_import(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    user_id: UUID,
    account_id: UUID,
    file_name: str,
    content: bytes,
    parser_name: str = "bank_csv",
) -> ImportBatch:
    """Parse, deduplicate, and persist one uploaded statement."""
    if parser_name not in PARSER_REGISTRY:
        raise UnknownParserError(parser_name)
    parser = PARSER_REGISTRY[parser_name]

    account = (
        await session.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise LookupError("Account not found")
    if not account.is_active:
        raise InactiveAccountError(account.name)

    batch_id = uuid.uuid4()
    safe_name = sanitize_filename(file_name)
    raw_key = f"raw/{user_id}/{batch_id}/{safe_name}"
    batch = ImportBatch(
        id=batch_id,
        user_id=user_id,
        account_id=account_id,
        parser_name=parser_name,
        file_name=safe_name,
        file_sha256=sha256_hex(content),
        raw_object_key=raw_key,
        file_size_bytes=len(content),
        status="processing",
    )
    session.add(batch)
    await session.flush()

    storage.put_object(raw_key, content, "text/csv")

    try:
        parsed: ParseResult = parser(content)
    except UnsupportedStatementError as exc:
        batch.status = "failed"
        batch.error_summary = {"parse_error": str(exc)}
        batch.completed_at = datetime.now(UTC)
        await session.flush()
        return batch

    if parsed.total_rows == 0:
        batch.status = "failed"
        batch.error_summary = {"parse_error": "The file contains no data rows"}
        batch.completed_at = datetime.now(UTC)
        await session.flush()
        return batch

    rows = _build_rows(parsed, user_id=user_id, account_id=account_id)
    fingerprints = [str(row["fingerprint"]) for row in rows]
    existing = await _existing_fingerprints(session, user_id, fingerprints)

    inserted = 0
    duplicates = 0
    for row in rows:
        fingerprint = str(row["fingerprint"])
        if fingerprint in existing:
            row["is_duplicate"] = True
            duplicates += 1
            continue
        existing.add(fingerprint)
        inserted += 1
        session.add(
            FinancialTransaction(
                user_id=user_id,
                account_id=account_id,
                import_batch_id=batch_id,
                transaction_date=date.fromisoformat(str(row["transaction_date"])),
                direction=str(row["direction"]),
                amount=Decimal(str(row["amount"])),
                description_raw=str(row["description_raw"]),
                description_clean=str(row["description_clean"]),
                reference_number=str(row["reference_number"]) or None,
                fingerprint=fingerprint,
                categorisation_source="uncategorised",
                is_transfer=False,
            )
        )

    for error in parsed.errors:
        session.add(
            ImportRowError(
                user_id=user_id,
                import_batch_id=batch_id,
                row_number=error.row_number,
                error_code=error.error_code,
                error_message=error.error_message,
                raw_row=error.raw_row,
            )
        )

    parquet_key = f"parsed/{user_id}/{batch_id}/rows.parquet"
    storage.put_object(
        parquet_key,
        records_to_parquet_bytes(rows),
        "application/vnd.apache.parquet",
    )

    error_codes = Counter(error.error_code for error in parsed.errors)
    summary: dict[str, Any] | None = None
    if parsed.errors or parsed.warnings:
        summary = {
            "by_code": dict(error_codes),
            "warnings": parsed.warnings,
            "detected_columns": parsed.detected_columns,
        }

    batch.total_rows = parsed.total_rows
    batch.inserted_rows = inserted
    batch.duplicate_rows = duplicates
    batch.error_rows = len(parsed.errors)
    batch.parsed_parquet_key = parquet_key
    batch.error_summary = summary
    if parsed.errors and (inserted > 0 or duplicates > 0):
        batch.status = "partial_failed"
    elif parsed.errors:
        batch.status = "failed"
    else:
        batch.status = "completed"
    batch.completed_at = datetime.now(UTC)
    await session.flush()
    return batch


async def list_batches(
    session: AsyncSession, user_id: UUID, *, account_id: UUID | None = None, limit: int = 50
) -> list[ImportBatch]:
    """Return recent import batches for a user, newest first."""
    stmt = select(ImportBatch).where(ImportBatch.user_id == user_id)
    if account_id is not None:
        stmt = stmt.where(ImportBatch.account_id == account_id)
    stmt = stmt.order_by(ImportBatch.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_batch(
    session: AsyncSession, user_id: UUID, batch_id: UUID
) -> ImportBatch | None:
    """Fetch one import batch scoped to the current user."""
    return (
        await session.execute(
            select(ImportBatch).where(
                ImportBatch.id == batch_id,
                ImportBatch.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def list_row_errors(
    session: AsyncSession, user_id: UUID, batch_id: UUID
) -> list[ImportRowError]:
    """Return all row errors for a batch ordered by original line number."""
    stmt = (
        select(ImportRowError)
        .where(
            ImportRowError.user_id == user_id,
            ImportRowError.import_batch_id == batch_id,
        )
        .order_by(ImportRowError.row_number)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _next_free_occurrence_index(
    session: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    transaction_date: date,
    amount: Decimal,
    direction: str,
    description_clean: str,
    reference_number: str | None,
) -> tuple[int, str]:
    for index in range(10_000):
        fingerprint = compute_fingerprint(
            user_id=str(user_id),
            account_id=str(account_id),
            transaction_date=transaction_date,
            amount=amount,
            direction=direction,
            description_clean=description_clean,
            reference_number=reference_number,
            occurrence_index=index,
        )
        existing = (
            await session.execute(
                select(FinancialTransaction.id)
                .where(
                    FinancialTransaction.user_id == user_id,
                    FinancialTransaction.fingerprint == fingerprint,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is None:
            return index, fingerprint
    raise RuntimeError("Could not allocate a unique fingerprint occurrence index")


async def resolve_row_error(
    session: AsyncSession,
    user_id: UUID,
    batch_id: UUID,
    error_id: UUID,
    *,
    resolution: str,
    corrected_payload: dict[str, Any] | None,
) -> ImportRowError | None:
    """Apply a correction or ignore decision to a row error.

    Returns ``None`` when the error is not visible to the current user.
    """
    error = (
        await session.execute(
            select(ImportRowError).where(
                ImportRowError.id == error_id,
                ImportRowError.user_id == user_id,
                ImportRowError.import_batch_id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if error is None:
        return None
    if error.resolution_status != "open":
        raise ValueError("Row error has already been resolved")

    batch = await get_batch(session, user_id, batch_id)
    if batch is None:
        return None

    if resolution == "corrected":
        if corrected_payload is None:
            raise ValueError("corrected_payload is required")
        transaction_date = date.fromisoformat(str(corrected_payload["transaction_date"]))
        direction = str(corrected_payload["direction"])
        amount = Decimal(str(corrected_payload["amount"]))
        description_raw = str(corrected_payload["description_raw"])
        description_clean = str(
            corrected_payload.get("description_clean") or clean_description(description_raw)
        )
        reference_number = corrected_payload.get("reference_number")
        reference_text = str(reference_number).strip() if reference_number else None

        _, fingerprint = await _next_free_occurrence_index(
            session,
            user_id=user_id,
            account_id=batch.account_id,
            transaction_date=transaction_date,
            amount=amount,
            direction=direction,
            description_clean=description_clean,
            reference_number=reference_text,
        )
        session.add(
            FinancialTransaction(
                user_id=user_id,
                account_id=batch.account_id,
                import_batch_id=batch.id,
                transaction_date=transaction_date,
                direction=direction,
                amount=amount,
                description_raw=description_raw,
                description_clean=description_clean,
                reference_number=reference_text,
                fingerprint=fingerprint,
                categorisation_source="uncategorised",
                is_transfer=False,
            )
        )
        error.resolution_status = "corrected"
        error.corrected_payload = corrected_payload
        batch.inserted_rows = batch.inserted_rows + 1
    else:
        error.resolution_status = "ignored"

    error.resolved_at = datetime.now(UTC)
    await session.flush()

    open_errors = (
        await session.execute(
            select(func.count(ImportRowError.id)).where(
                ImportRowError.import_batch_id == batch_id,
                ImportRowError.resolution_status == "open",
            )
        )
    ).scalar_one()
    if int(open_errors) == 0:
        batch.status = "completed"
    await session.flush()
    return error
