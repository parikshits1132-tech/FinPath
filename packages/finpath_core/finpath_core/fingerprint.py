"""Deterministic transaction description cleaning and fingerprinting.

The fingerprint deliberately includes an ``occurrence_index`` so that two genuinely
identical transactions in one statement (for example two INR 200 coffees on the same
day) are both preserved, while re-importing the same statement produces the exact
same fingerprints and therefore skips both rows as duplicates.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from finpath_core.types import INR, quantize_inr

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_description(raw: str) -> str:
    """Normalise a statement narration without discarding meaningful characters.

    The function is deterministic and idempotent: running it twice returns the same
    string. Unicode is normalised with NFKC, non-breaking spaces become regular
    spaces, control characters are removed, and internal whitespace is collapsed.
    """
    value = unicodedata.normalize("NFKC", raw or "")
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    value = _CONTROL_RE.sub("", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def canonical_amount(amount: Decimal | int | str) -> str:
    """Return a stable 4-decimal string used inside fingerprint payloads."""
    try:
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except InvalidOperation as exc:  # pragma: no cover - defensive for bad API callers
        raise ValueError(f"Invalid monetary amount: {amount!r}") from exc
    return format(quantize_inr(value), "f")


def compute_fingerprint(
    *,
    user_id: str,
    account_id: str,
    transaction_date: date,
    amount: Decimal | int | str,
    direction: str,
    description_clean: str,
    reference_number: str | None = None,
    occurrence_index: int = 0,
    currency: str = INR,
) -> str:
    """Compute the SHA-256 fingerprint for a canonical transaction tuple.

    ``occurrence_index`` is the zero-based position among identical tuples inside a
    single file/batch. It must not be derived from database state, otherwise the
    same file imported twice would produce different fingerprints.
    """
    if direction not in ("debit", "credit"):
        raise ValueError(f"Unsupported direction: {direction!r}")
    if occurrence_index < 0:
        raise ValueError("occurrence_index must be non-negative")

    payload: list[Any] = [
        str(user_id),
        str(account_id),
        transaction_date.isoformat(),
        canonical_amount(amount),
        currency,
        direction,
        clean_description(description_clean),
        (reference_number or "").strip(),
        occurrence_index,
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_occurrence_key(
    *,
    transaction_date: date,
    amount: Decimal | int | str,
    direction: str,
    description_clean: str,
    reference_number: str | None = None,
    currency: str = INR,
) -> tuple[str, str, str, str, str, str]:
    """Return the tuple used to count identical rows within one import batch."""
    return (
        transaction_date.isoformat(),
        canonical_amount(amount),
        currency,
        direction,
        clean_description(description_clean),
        (reference_number or "").strip(),
    )
