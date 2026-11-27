"""Unit tests for the deterministic synthetic dataset generator."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
from finpath_core.ingestion import parse_bank_csv
from finpath_core.synthetic import generate_dataset, write_dataset


def test_generator_is_deterministic_and_dated() -> None:
    """The same seed produces identical users, counts, and transaction rows."""
    first = generate_dataset(num_users=5, months=12, seed=7, end_month=date(2026, 3, 1))
    second = generate_dataset(num_users=5, months=12, seed=7, end_month=date(2026, 3, 1))

    assert first.summary() == second.summary()
    assert first.users == second.users
    assert first.transactions[:20] == second.transactions[:20]
    assert len(first.users) == 5
    assert len(first.accounts) == 15
    assert first.start_month == date(2025, 4, 1)
    assert first.end_month == date(2026, 3, 1)
    assert len(first.transactions) > 300
    assert len(first.assets) == 5 * 2 * 12
    assert len(first.liabilities) == (3 + 2) * 12  # 3 home loans + 2 auto loans

    transaction_dates = {row["transaction_date"] for row in first.transactions}
    assert min(transaction_dates) >= "2025-04-01"
    assert max(transaction_dates) <= "2026-03-28"


def test_different_seed_changes_data() -> None:
    """A different seed yields a different dataset."""
    first = generate_dataset(num_users=3, months=2, seed=1, end_month=date(2026, 3, 1))
    second = generate_dataset(num_users=3, months=2, seed=2, end_month=date(2026, 3, 1))
    assert first.transactions != second.transactions


def test_written_statements_are_parseable_and_parquet_matches(tmp_path: Path) -> None:
    """Generated CSV statements round-trip through the parser and Parquet is readable."""
    dataset = generate_dataset(num_users=2, months=3, seed=11, end_month=date(2026, 3, 1))
    paths = write_dataset(dataset, tmp_path / "synthetic")

    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    assert manifest["users"] == 2
    assert manifest["transactions"] == len(dataset.transactions)

    statement_files = sorted((tmp_path / "synthetic" / "statements").glob("*.csv"))
    assert len(statement_files) == 6
    parsed_rows = 0
    for statement in statement_files:
        result = parse_bank_csv(statement.read_bytes())
        assert result.errors == []
        parsed_rows += len(result.transactions)
    assert parsed_rows == len(dataset.transactions)

    table = pq.read_table(paths["transactions_parquet"])
    assert table.num_rows == len(dataset.transactions)
    assert set(table.column_names) >= {"user_key", "account_key", "amount", "direction"}

    with (tmp_path / "synthetic" / "users.json").open(encoding="utf-8") as handle:
        users = json.load(handle)
    assert len(users) == 2
    assert users[0]["email"].endswith("@finpath.demo")


def test_generated_csv_contains_debit_and_credit_columns(tmp_path: Path) -> None:
    """Statement shape is what the import UI will accept."""
    dataset = generate_dataset(num_users=1, months=1, seed=3, end_month=date(2026, 3, 1))
    write_dataset(dataset, tmp_path)
    statement = next((tmp_path / "statements").glob("*-savings.csv"))
    with statement.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == ["Date", "Description", "Debit", "Credit", "Reference"]
