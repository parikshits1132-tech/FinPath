"""Flexible bank statement CSV parser.

The MVP targets Indian bank exports, which vary wildly in header naming while
sharing the same core shape: a date, a narration, and either a debit/credit column
pair or a signed amount column. Column aliases and date/amount formats are kept in
this module so new bank samples can be supported without touching the API layer.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from finpath_core.fingerprint import clean_description
from finpath_core.types import quantize_inr


class UnsupportedStatementError(ValueError):
    """Raised when a CSV does not expose the minimum columns we can parse."""


@dataclass(frozen=True)
class ParsedTransaction:
    """A successfully parsed statement row."""

    row_number: int
    transaction_date: date
    direction: str
    amount: Decimal
    description_raw: str
    description_clean: str
    reference_number: str | None


@dataclass(frozen=True)
class RowError:
    """A row that could not be converted into a transaction."""

    row_number: int
    error_code: str
    error_message: str
    raw_row: dict[str, str]


@dataclass(frozen=True)
class ParseResult:
    """Outcome of parsing one CSV file."""

    total_rows: int
    transactions: list[ParsedTransaction]
    errors: list[RowError]
    detected_columns: dict[str, str | None]
    delimiter: str = ","
    header_line_number: int = 1
    warnings: list[str] = field(default_factory=list)


COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "txn date",
        "transaction date",
        "value date",
        "post date",
        "posting date",
        "date of transaction",
    ),
    "description": (
        "description",
        "narration",
        "particulars",
        "transaction remarks",
        "remarks",
        "details",
        "transaction details",
        "transaction description",
    ),
    "debit": (
        "debit",
        "debits",
        "debit amount",
        "withdrawal",
        "withdrawals",
        "withdrawal amt",
        "withdrawal amount",
        "withdrawal amt inr",
        "dr",
        "paid out",
    ),
    "credit": (
        "credit",
        "credits",
        "credit amount",
        "deposit",
        "deposits",
        "deposit amt",
        "deposit amount",
        "deposit amt inr",
        "cr",
        "paid in",
    ),
    "amount": (
        "amount",
        "transaction amount",
        "amt",
        "amount inr",
    ),
    "type": (
        "type",
        "dr cr",
        "dr cr flag",
        "drcr",
        "transaction type",
        "debit credit",
        "cr dr",
    ),
    "reference": (
        "reference",
        "reference number",
        "ref no",
        "ref",
        "cheque no",
        "chq no",
        "chq ref no",
        "cheque ref no",
        "cheque number",
        "transaction id",
        "txn id",
        "utr",
        "utr no",
    ),
}

_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%m/%d/%Y",
    "%m-%d-%Y",
)

_DEBIT_HINTS = frozenset({"d", "dr", "debit", "w", "withdrawal", "paid out"})
_CREDIT_HINTS = frozenset({"c", "cr", "credit", "dep", "deposit", "paid in"})
_AMOUNT_CLEAN_RE = re.compile(r"[^0-9.\-]")
_DIRECTION_SUFFIX_RE = re.compile(r"^(?P<value>.*?)[\s]*(?P<hint>dr|cr)\.?$", re.IGNORECASE)


def _normalise_header(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedStatementError("Could not decode file as text")


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _detect_columns(headers: list[str]) -> dict[str, str | None]:
    normalised = {_normalise_header(h): h for h in headers if h and h.strip()}
    detected: dict[str, str | None] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        detected[canonical] = None
        for alias in aliases:
            if alias in normalised:
                detected[canonical] = normalised[alias]
                break
    return detected


def _looks_like_header(row: list[str]) -> bool:
    detected = _detect_columns([cell for cell in row if cell])
    has_date = detected["date"] is not None
    has_shape = any(
        detected[column] is not None for column in ("description", "debit", "credit", "amount")
    )
    return has_date and has_shape


def _find_header_line(lines: list[str], delimiter: str, max_scan: int = 25) -> int | None:
    reader = csv.reader(lines, delimiter=delimiter)
    for index, row in enumerate(reader):
        if index >= max_scan:
            break
        if _looks_like_header(row):
            return index
    return None


def _parse_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Parse Indian-formatted amounts, returning ``None`` when the cell is empty."""
    value = raw.strip().replace("\u20b9", "").replace("INR", "").replace("Rs.", "")
    if not value or value in {"-", "--", "NA", "N/A"}:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    value = _AMOUNT_CLEAN_RE.sub("", value)
    if not value or value in {"-", "."}:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    if negative:
        amount = -amount
    return quantize_inr(amount)


def _extract_direction_suffix(raw: str) -> tuple[str, str | None]:
    match = _DIRECTION_SUFFIX_RE.match(raw.strip())
    if match and match.group("hint"):
        return match.group("value"), match.group("hint").lower()
    return raw, None


def _direction_from_hint(hint: str | None) -> str | None:
    if not hint:
        return None
    normalised = _normalise_header(hint)
    if normalised in _DEBIT_HINTS:
        return "debit"
    if normalised in _CREDIT_HINTS:
        return "credit"
    return None


def _cell(row: dict[str, str], detected: dict[str, str | None], key: str) -> str:
    header = detected.get(key)
    if header is None:
        return ""
    return (row.get(header) or "").strip()


def parse_bank_csv(data: bytes) -> ParseResult:
    """Parse a bank statement CSV into canonical transactions and row errors."""
    if not data:
        raise UnsupportedStatementError("The uploaded file is empty")

    text = _decode(data)
    lines = text.splitlines()
    delimiter = _detect_delimiter("\n".join(lines[:5]))
    header_index = _find_header_line(lines, delimiter)
    if header_index is None:
        raise UnsupportedStatementError(
            "Could not find a CSV header containing a date and description/debit/credit columns"
        )

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    detected = _detect_columns(list(reader.fieldnames or []))
    if detected["date"] is None:
        raise UnsupportedStatementError("No transaction date column was detected")
    has_split_amounts = detected["debit"] is not None or detected["credit"] is not None
    if detected["description"] is None or (not has_split_amounts and detected["amount"] is None):
        raise UnsupportedStatementError(
            "CSV must contain a description column and either debit/credit or amount columns"
        )

    transactions: list[ParsedTransaction] = []
    errors: list[RowError] = []
    total_rows = 0
    warnings: list[str] = []

    if detected["debit"] and detected["credit"]:
        warnings.append("Both debit and credit columns detected; preview both for balance.")

    for offset, row in enumerate(reader):
        row_number = header_index + offset + 2
        if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue
        total_rows += 1

        raw_row = {
            str(key): (value if isinstance(value, str) else "")
            for key, value in row.items()
            if key is not None
        }

        raw_date = _cell(row, detected, "date")
        transaction_date = _parse_date(raw_date)
        if transaction_date is None:
            errors.append(
                RowError(
                    row_number=row_number,
                    error_code="INVALID_DATE",
                    error_message=f"Unrecognised transaction date: {raw_date!r}",
                    raw_row=raw_row,
                )
            )
            continue

        description_raw = _cell(row, detected, "description")
        if not description_raw:
            errors.append(
                RowError(
                    row_number=row_number,
                    error_code="MISSING_DESCRIPTION",
                    error_message="Transaction description is empty",
                    raw_row=raw_row,
                )
            )
            continue

        reference = _cell(row, detected, "reference") or None
        type_hint = _direction_from_hint(_cell(row, detected, "type"))

        direction: str | None = None
        amount: Decimal | None = None

        if has_split_amounts:
            debit_raw, debit_hint = _extract_direction_suffix(_cell(row, detected, "debit"))
            credit_raw, credit_hint = _extract_direction_suffix(_cell(row, detected, "credit"))
            debit = _parse_amount(debit_raw)
            credit = _parse_amount(credit_raw)
            debit_value = abs(debit) if debit is not None else Decimal("0")
            credit_value = abs(credit) if credit is not None else Decimal("0")

            if debit_value > 0 and credit_value > 0:
                errors.append(
                    RowError(
                        row_number=row_number,
                        error_code="AMBIGUOUS_AMOUNT",
                        error_message="Both debit and credit columns contain a value",
                        raw_row=raw_row,
                    )
                )
                continue
            if debit_value > 0:
                direction, amount = "debit", debit_value
            elif credit_value > 0:
                direction, amount = "credit", credit_value

            # Some exports put "Dr"/"Cr" in the amount cell instead of a type column.
            if direction is None:
                direction = _direction_from_hint(debit_hint) or _direction_from_hint(credit_hint)
                if direction == "debit" or direction == "credit":
                    amount = debit_value or credit_value
        else:
            amount_raw, amount_hint = _extract_direction_suffix(_cell(row, detected, "amount"))
            parsed_amount = _parse_amount(amount_raw)
            if parsed_amount is not None:
                if parsed_amount < 0:
                    direction, amount = "debit", abs(parsed_amount)
                elif parsed_amount > 0:
                    amount = parsed_amount
                    direction = type_hint or _direction_from_hint(amount_hint)

        if direction is None and amount is None:
            errors.append(
                RowError(
                    row_number=row_number,
                    error_code="MISSING_AMOUNT",
                    error_message="Row has no debit, credit, or amount value",
                    raw_row=raw_row,
                )
            )
            continue
        if direction is None:
            errors.append(
                RowError(
                    row_number=row_number,
                    error_code="MISSING_DIRECTION",
                    error_message="Could not determine whether the row is a debit or credit",
                    raw_row=raw_row,
                )
            )
            continue
        if amount is None or amount <= 0:
            errors.append(
                RowError(
                    row_number=row_number,
                    error_code="INVALID_AMOUNT",
                    error_message=f"Amount must be positive, got {amount!r}",
                    raw_row=raw_row,
                )
            )
            continue

        transactions.append(
            ParsedTransaction(
                row_number=row_number,
                transaction_date=transaction_date,
                direction=direction,
                amount=quantize_inr(amount),
                description_raw=description_raw,
                description_clean=clean_description(description_raw),
                reference_number=reference,
            )
        )

    return ParseResult(
        total_rows=total_rows,
        transactions=transactions,
        errors=errors,
        detected_columns=detected,
        delimiter=delimiter,
        header_line_number=header_index + 1,
        warnings=warnings,
    )
