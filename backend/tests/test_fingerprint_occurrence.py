"""Unit tests for deterministic fingerprints and occurrence counting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from finpath_core.fingerprint import (
    canonical_amount,
    clean_description,
    compute_fingerprint,
    fingerprint_occurrence_key,
)


def test_fingerprint_is_deterministic_and_occurrence_aware() -> None:
    """Identical tuples get distinct fingerprints per occurrence index, reproducibly."""
    common = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "account_id": "22222222-2222-2222-2222-222222222222",
        "transaction_date": date(2026, 4, 1),
        "amount": Decimal("200.0000"),
        "direction": "debit",
        "description_clean": "UPI CHAI POINT",
        "reference_number": None,
    }
    first = compute_fingerprint(**common, occurrence_index=0)
    second = compute_fingerprint(**common, occurrence_index=1)

    assert first != second
    assert first == compute_fingerprint(**common, occurrence_index=0)
    assert len(first) == 64
    assert int(first, 16) >= 0  # valid lowercase hex


def test_same_day_duplicates_within_one_file_are_preserved() -> None:
    """Two identical INR 200 rows map to indices 0 and 1, not one collapsed row."""
    common = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "account_id": "22222222-2222-2222-2222-222222222222",
        "transaction_date": date(2026, 4, 1),
        "amount": Decimal("200.0000"),
        "direction": "debit",
        "description_clean": "UPI CHAI POINT",
        "reference_number": "UPI123",
    }
    key = fingerprint_occurrence_key(
        transaction_date=common["transaction_date"],
        amount=common["amount"],
        direction=common["direction"],
        description_clean=common["description_clean"],
        reference_number=common["reference_number"],
    )
    assert key == (
        "2026-04-01",
        "200.0000",
        "INR",
        "debit",
        "UPI CHAI POINT",
        "UPI123",
    )
    fingerprints = [compute_fingerprint(**common, occurrence_index=index) for index in (0, 1)]
    assert fingerprints[0] != fingerprints[1]
    assert fingerprints == [
        compute_fingerprint(**common, occurrence_index=index) for index in (0, 1)
    ]


def test_description_cleaning_is_stable_and_normalises_unicode() -> None:
    """Cleaning collapses whitespace, removes NBSP, and is idempotent."""
    cleaned = clean_description("  UPI   ZEPTO\u00a0GROCERIES \u200b ")
    assert cleaned == "UPI ZEPTO GROCERIES"
    assert clean_description(cleaned) == cleaned


def test_canonical_amount_is_fixed_precision() -> None:
    """Amounts canonicalise to 4 decimals so Decimal inputs are byte-stable."""
    assert canonical_amount("200") == "200.0000"
    assert canonical_amount(Decimal("200.45678")) == "200.4568"


def test_fingerprint_rejects_invalid_direction() -> None:
    """Only debit and credit directions are accepted."""
    with pytest.raises(ValueError):
        compute_fingerprint(
            user_id="u",
            account_id="a",
            transaction_date=date(2026, 4, 1),
            amount=Decimal("1"),
            direction="sideways",
            description_clean="x",
        )
