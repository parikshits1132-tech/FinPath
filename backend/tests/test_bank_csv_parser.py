"""Unit tests for the flexible Indian bank CSV parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from finpath_core.ingestion import UnsupportedStatementError, parse_bank_csv


def test_parses_debit_credit_statement_with_preamble_and_aliases() -> None:
    """Header aliases, preamble lines, and Indian amount formatting are supported."""
    csv_text = (
        "HDFC Bank Statement\n"
        "Account XXXXXXXX1234\n"
        "\n"
        "Txn Date,Narration,Withdrawal Amt.,Deposit Amt.,Chq/Ref No\n"
        '01/04/2026,"UPI-ZEPTO-GROCERIES","1,250.50",,\n'
        '02/04/2026,SALARY CREDIT,,"1,20,000.00",SAL001\n'
        "03/04/2026,ATM WDL,5000,,,ATM9\n"
    )
    result = parse_bank_csv(csv_text.encode("utf-8"))

    assert result.total_rows == 3
    assert result.header_line_number == 4
    assert result.detected_columns["debit"] == "Withdrawal Amt."
    assert result.detected_columns["credit"] == "Deposit Amt."
    assert result.detected_columns["reference"] == "Chq/Ref No"
    assert [tx.direction for tx in result.transactions] == ["debit", "credit", "debit"]
    assert result.transactions[0].amount == Decimal("1250.5000")
    assert result.transactions[1].amount == Decimal("120000.0000")
    assert result.transactions[1].transaction_date == date(2026, 4, 2)
    assert result.errors == []


def test_single_signed_amount_column_and_type_hint() -> None:
    """A signed amount column uses its sign, while a DR/CR helper drives direction."""
    signed = (
        "Date,Description,Amount\n"
        "01-04-2026,SWIGGY ORDER,-450.00\n"
        "02-04-2026,SALARY,120000.00\n"
    )
    with_type = signed.split("\n")[0].replace(",Amount", ",Amount,DR/CR") + "\n" + "\n".join(
        f"{line},CR" if "SALARY" in line else f"{line},DR"
        for line in signed.split("\n")[1:]
        if line
    )

    signed_result = parse_bank_csv(signed.encode("utf-8"))
    assert [tx.direction for tx in signed_result.transactions] == ["debit"]
    assert len(signed_result.errors) == 1
    assert signed_result.errors[0].error_code == "MISSING_DIRECTION"

    typed_result = parse_bank_csv(with_type.encode("utf-8"))
    assert [tx.direction for tx in typed_result.transactions] == ["debit", "credit"]
    assert typed_result.transactions[0].amount == Decimal("450.0000")
    assert typed_result.errors == []


def test_row_errors_are_classified() -> None:
    """Invalid dates, missing descriptions, and duplicate amounts produce row errors."""
    csv_text = (
        "Date,Description,Debit,Credit\n"
        "31/02/2026,BAD DATE,100,\n"
        "01/04/2026,,100,\n"
        "02/04/2026,BOTH SIDES,100,50\n"
        "03/04/2026,NO AMOUNT,,\n"
        "04/04/2026,GOOD ROW,10.00,\n"
    )
    result = parse_bank_csv(csv_text.encode("utf-8"))
    assert result.total_rows == 5
    assert len(result.transactions) == 1
    assert [error.error_code for error in result.errors] == [
        "INVALID_DATE",
        "MISSING_DESCRIPTION",
        "AMBIGUOUS_AMOUNT",
        "MISSING_AMOUNT",
    ]
    assert result.errors[0].row_number == 2
    assert result.errors[0].raw_row["Description"] == "BAD DATE"


def test_unsupported_statement_raises() -> None:
    """A CSV without recognisable columns is rejected before any writes."""
    with pytest.raises(UnsupportedStatementError):
        parse_bank_csv(b"Foo,Bar\n1,2\n")


def test_empty_file_raises() -> None:
    """Empty uploads fail fast."""
    with pytest.raises(UnsupportedStatementError):
        parse_bank_csv(b"")
