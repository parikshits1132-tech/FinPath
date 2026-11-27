"""Deterministic synthetic FinPath dataset generator.

The generator is intentionally pure (no database, network, or wall-clock reads) so
the same seed always produces byte-identical data. It emits per-account bank CSV
statements, JSON reference files, and an all-transactions Parquet file.

Run it with::

    python -m finpath_core.synthetic --output-dir data/synthetic --users 100
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from finpath_core.fingerprint import clean_description
from finpath_core.parquet import write_parquet_file
from finpath_core.types import INR, quantize_inr

FIRST_NAMES = (
    "Aarav",
    "Ananya",
    "Arjun",
    "Diya",
    "Ishaan",
    "Kavya",
    "Kabir",
    "Meera",
    "Neha",
    "Rohan",
    "Priya",
    "Siddharth",
    "Sneha",
    "Vikram",
    "Aditi",
    "Rahul",
    "Pooja",
    "Nikhil",
    "Shreya",
    "Manish",
)

LAST_NAMES = (
    "Sharma",
    "Verma",
    "Patel",
    "Iyer",
    "Nair",
    "Gupta",
    "Reddy",
    "Mehta",
    "Joshi",
    "Singh",
    "Kulkarni",
    "Chatterjee",
    "Rao",
    "Desai",
    "Mishra",
)

INSTITUTIONS = ("HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank", "Kotak Bank")

GROCERY_MERCHANTS = ("BigBasket", "Zepto", "Blinkit", "DMart", "Reliance Fresh")
DINING_MERCHANTS = ("Swiggy", "Zomato", "Third Wave Coffee", "Blue Tokai")
UTILITY_MERCHANTS = ("Airtel Postpaid", "Jio Fiber", "Tata Power", "BWSSB Water")
FUEL_MERCHANTS = ("Indian Oil", "HP Petrol Pump", "Shell Fuel")
SHOPPING_MERCHANTS = ("Amazon India", "Flipkart", "Myntra", "Decathlon")
SUBSCRIPTION_MERCHANTS = ("Netflix", "Spotify", "Google One", "Cult.fit")

ASSET_CLASSES = ("fixed_deposit", "gold", "real_estate", "epf_ppf")


@dataclass(frozen=True)
class SyntheticDataset:
    """In-memory synthetic dataset with JSON-friendly records."""

    seed: int
    start_month: date
    end_month: date
    users: list[dict[str, Any]] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    liabilities: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return counts and provenance metadata for a manifest file."""
        return {
            "seed": self.seed,
            "start_month": self.start_month.isoformat(),
            "end_month": self.end_month.isoformat(),
            "users": len(self.users),
            "accounts": len(self.accounts),
            "transactions": len(self.transactions),
            "asset_valuations": len(self.assets),
            "liability_valuations": len(self.liabilities),
        }


def _month_sequence(end_month: date, months: int) -> list[date]:
    if months < 1:
        raise ValueError("months must be at least 1")
    end = date(end_month.year, end_month.month, 1)
    sequence: list[date] = []
    year, month = end.year, end.month
    for _ in range(months):
        sequence.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(sequence))


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    """Return a random rupee amount in ``[low, high]`` with 2 paise precision."""
    paise = rng.randint(low * 100, high * 100)
    return quantize_inr(Decimal(paise) / Decimal(100))


def _amount_text(amount: Decimal) -> str:
    return format(quantize_inr(amount), "f")


def _safe_day(rng: random.Random, month: date, low: int = 1, high: int = 28) -> date:
    return date(month.year, month.month, rng.randint(low, high))


def _add_transaction(
    rows: list[dict[str, Any]],
    *,
    user_key: str,
    account_key: str,
    transaction_date: date,
    direction: str,
    amount: Decimal,
    description: str,
    reference: str | None,
) -> None:
    rows.append(
        {
            "user_key": user_key,
            "account_key": account_key,
            "transaction_date": transaction_date.isoformat(),
            "direction": direction,
            "amount": _amount_text(amount),
            "currency": INR,
            "description_raw": description,
            "description_clean": clean_description(description),
            "reference_number": reference or "",
        }
    )


def generate_dataset(
    *,
    num_users: int = 100,
    months: int = 12,
    seed: int = 42,
    end_month: date | None = None,
) -> SyntheticDataset:
    """Generate a deterministic synthetic dataset."""
    if num_users < 1:
        raise ValueError("num_users must be at least 1")
    rng = random.Random(seed)
    end = end_month or date.today().replace(day=1)
    month_sequence = _month_sequence(end, months)
    first_month = month_sequence[0]

    users: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    liabilities: list[dict[str, Any]] = []

    for index in range(num_users):
        user_key = f"user-{index:03d}"
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index * 7 + 3) % len(LAST_NAMES)]
        full_name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}.{index:03d}@finpath.demo"
        users.append(
            {
                "user_key": user_key,
                "email": email,
                "full_name": full_name,
                "base_currency": INR,
                "demo_password": "FinPath@1234",
            }
        )

        institution = INSTITUTIONS[index % len(INSTITUTIONS)]
        savings_key = f"{user_key}-savings"
        card_key = f"{user_key}-card"
        wallet_key = f"{user_key}-wallet"
        opening_savings = _money(rng, 25_000, 250_000)
        opening_date = first_month.isoformat()

        accounts.extend(
            [
                {
                    "account_key": savings_key,
                    "user_key": user_key,
                    "name": f"{first}'s Savings",
                    "account_type": "savings",
                    "institution_name": institution,
                    "masked_account_number": f"XXXX{rng.randint(1000, 9999)}",
                    "currency": INR,
                    "opening_balance": _amount_text(opening_savings),
                    "opening_balance_date": opening_date,
                },
                {
                    "account_key": card_key,
                    "user_key": user_key,
                    "name": f"{first}'s Credit Card",
                    "account_type": "credit_card",
                    "institution_name": institution,
                    "masked_account_number": f"XXXX{rng.randint(1000, 9999)}",
                    "currency": INR,
                    "opening_balance": "0.0000",
                    "opening_balance_date": opening_date,
                },
                {
                    "account_key": wallet_key,
                    "user_key": user_key,
                    "name": "UPI Wallet",
                    "account_type": "wallet",
                    "institution_name": "Paytm",
                    "masked_account_number": None,
                    "currency": INR,
                    "opening_balance": "500.0000",
                    "opening_balance_date": opening_date,
                },
            ]
        )

        monthly_salary = _money(rng, 55_000, 260_000)
        rent = _money(rng, 12_000, 48_000)
        card_payment = Decimal("0")

        for month_index, month in enumerate(month_sequence):
            reference_seq = index * 100_000 + month_index * 1_000

            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=savings_key,
                transaction_date=_safe_day(rng, month, 1, 2),
                direction="credit",
                amount=monthly_salary,
                description=f"SALARY CREDIT - {institution.upper()} SALARY",
                reference=f"UTR{reference_seq + 1:09d}",
            )
            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=savings_key,
                transaction_date=_safe_day(rng, month, 2, 5),
                direction="debit",
                amount=rent,
                description="NEFT DR RENT PAYMENT LANDLORD",
                reference=f"UTR{reference_seq + 2:09d}",
            )

            for merchant in rng.sample(GROCERY_MERCHANTS, k=rng.randint(2, 4)):
                _add_transaction(
                    transactions,
                    user_key=user_key,
                    account_key=savings_key,
                    transaction_date=_safe_day(rng, month),
                    direction="debit",
                    amount=_money(rng, 250, 4_500),
                    description=f"UPI-{merchant.upper()}-{rng.randint(100000, 999999)}",
                    reference=f"UPI{reference_seq + rng.randint(10, 900):09d}",
                )

            for merchant in rng.sample(DINING_MERCHANTS, k=rng.randint(1, 3)):
                _add_transaction(
                    transactions,
                    user_key=user_key,
                    account_key=card_key,
                    transaction_date=_safe_day(rng, month),
                    direction="debit",
                    amount=_money(rng, 150, 2_600),
                    description=f"{merchant.upper()} ORDER {rng.randint(1000, 9999)}",
                    reference=f"TXN{reference_seq + rng.randint(10, 900):09d}",
                )

            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=savings_key,
                transaction_date=_safe_day(rng, month, 5, 12),
                direction="debit",
                amount=_money(rng, 500, 3_500),
                description=f"BILLPAY {rng.choice(UTILITY_MERCHANTS).upper()}",
                reference=f"BILL{reference_seq + 3:09d}",
            )
            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=card_key,
                transaction_date=_safe_day(rng, month, 8, 20),
                direction="debit",
                amount=_money(rng, 800, 4_000),
                description=f"FUEL {rng.choice(FUEL_MERCHANTS).upper()}",
                reference=f"POS{reference_seq + 4:09d}",
            )
            if rng.random() < 0.6:
                _add_transaction(
                    transactions,
                    user_key=user_key,
                    account_key=card_key,
                    transaction_date=_safe_day(rng, month),
                    direction="debit",
                    amount=_money(rng, 600, 12_000),
                    description=f"{rng.choice(SHOPPING_MERCHANTS).upper()} PURCHASE",
                    reference=f"TXN{reference_seq + rng.randint(10, 900):09d}",
                )

            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=card_key,
                transaction_date=_safe_day(rng, month, 1, 7),
                direction="debit",
                amount=_money(rng, 149, 1_499),
                description=f"{rng.choice(SUBSCRIPTION_MERCHANTS).upper()} SUBSCRIPTION",
                reference=f"SUB{reference_seq + 5:09d}",
            )

            if card_payment > 0:
                _add_transaction(
                    transactions,
                    user_key=user_key,
                    account_key=savings_key,
                    transaction_date=_safe_day(rng, month, 15, 20),
                    direction="debit",
                    amount=card_payment,
                    description="CREDIT CARD BILL PAYMENT",
                    reference=f"CCPAY{reference_seq + 6:09d}",
                )
                _add_transaction(
                    transactions,
                    user_key=user_key,
                    account_key=card_key,
                    transaction_date=_safe_day(rng, month, 15, 20),
                    direction="credit",
                    amount=card_payment,
                    description="PAYMENT RECEIVED - THANK YOU",
                    reference=f"CCPAY{reference_seq + 6:09d}",
                )
            card_payment = _money(rng, 2_000, 18_000)

            # Wallet top-ups and small UPI spends keep the wallet history realistic.
            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=wallet_key,
                transaction_date=_safe_day(rng, month, 3, 10),
                direction="credit",
                amount=_money(rng, 500, 5_000),
                description="UPI WALLET TOPUP FROM SAVINGS",
                reference=f"WLT{reference_seq + 7:09d}",
            )
            wallet_merchant = rng.choice(("CHAI POINT", "METRO CARD", "LOCAL KIRANA"))
            _add_transaction(
                transactions,
                user_key=user_key,
                account_key=wallet_key,
                transaction_date=_safe_day(rng, month),
                direction="debit",
                amount=_money(rng, 50, 700),
                description=f"UPI-{wallet_merchant}",
                reference=f"WLT{reference_seq + 8:09d}",
            )

        # A fixed deposit and gold holding, revalued monthly.
        fd_principal = _money(rng, 50_000, 500_000)
        gold_grams = Decimal(rng.randint(5, 120))
        gold_rate = _money(rng, 5_800, 7_400)
        for month_index, month in enumerate(month_sequence):
            fd_value = quantize_inr(
                fd_principal
                * (Decimal("1") + Decimal("0.065") * Decimal(month_index) / Decimal(12))
            )
            gold_value = quantize_inr(
                gold_grams * gold_rate * (Decimal("1") + Decimal(rng.randint(-4, 6)) / Decimal(100))
            )
            for asset_class, name, value in (
                ("fixed_deposit", "Emergency Fixed Deposit", fd_value),
                ("gold", "Gold Jewellery", gold_value),
            ):
                assets.append(
                    {
                        "user_key": user_key,
                        "name": name,
                        "asset_class": asset_class,
                        "current_value": _amount_text(value),
                        "currency": INR,
                        "valuation_date": date(month.year, month.month, 28).isoformat(),
                    }
                )

        if index % 2 == 0:
            principal = _money(rng, 800_000, 6_000_000)
            rate = quantize_inr(Decimal(rng.uniform(7.5, 10.5)))
            emi = _money(rng, 12_000, 55_000)
            for month_index, month in enumerate(month_sequence):
                outstanding = quantize_inr(
                    principal - principal * Decimal("0.008") * Decimal(month_index)
                )
                liabilities.append(
                    {
                        "user_key": user_key,
                        "name": "Home Loan",
                        "liability_type": "home_loan",
                        "principal_outstanding": _amount_text(max(outstanding, Decimal("0"))),
                        "interest_rate_annual": format(rate, "f"),
                        "emi_amount": _amount_text(emi),
                        "currency": INR,
                        "as_of_date": date(month.year, month.month, 28).isoformat(),
                    }
                )

        if index % 3 == 0:
            principal = _money(rng, 200_000, 1_500_000)
            rate = quantize_inr(Decimal(rng.uniform(9.0, 13.0)))
            for month_index, month in enumerate(month_sequence):
                outstanding = quantize_inr(
                    principal - principal * Decimal("0.015") * Decimal(month_index)
                )
                liabilities.append(
                    {
                        "user_key": user_key,
                        "name": "Auto Loan",
                        "liability_type": "auto_loan",
                        "principal_outstanding": _amount_text(max(outstanding, Decimal("0"))),
                        "interest_rate_annual": format(rate, "f"),
                        "emi_amount": _amount_text(_money(rng, 5_000, 22_000)),
                        "currency": INR,
                        "as_of_date": date(month.year, month.month, 28).isoformat(),
                    }
                )

    return SyntheticDataset(
        seed=seed,
        start_month=first_month,
        end_month=date(end.year, end.month, 1),
        users=users,
        accounts=accounts,
        transactions=transactions,
        assets=assets,
        liabilities=liabilities,
    )


def _write_json(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _write_statements(dataset: SyntheticDataset, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    by_account: dict[str, list[dict[str, Any]]] = {}
    for row in dataset.transactions:
        by_account.setdefault(str(row["account_key"]), []).append(row)

    for account_key, rows in by_account.items():
        path = directory / f"{account_key}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Date", "Description", "Debit", "Credit", "Reference"])
            for row in sorted(rows, key=lambda item: (item["transaction_date"], item["amount"])):
                amount = row["amount"]
                writer.writerow(
                    [
                        row["transaction_date"],
                        row["description_raw"],
                        amount if row["direction"] == "debit" else "",
                        amount if row["direction"] == "credit" else "",
                        row["reference_number"],
                    ]
                )
    return len(by_account)


def write_dataset(dataset: SyntheticDataset, output_dir: Path) -> dict[str, str]:
    """Write the dataset to CSV, JSON, and Parquet files and return the manifest paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(dataset.users, output_dir / "users.json")
    _write_json(dataset.accounts, output_dir / "accounts.json")
    _write_json(dataset.assets, output_dir / "assets.json")
    _write_json(dataset.liabilities, output_dir / "liabilities.json")
    transaction_records = [dict(row) for row in dataset.transactions]
    write_parquet_file(transaction_records, output_dir / "transactions.parquet")
    statement_count = _write_statements(dataset, output_dir / "statements")

    manifest = dataset.summary()
    manifest["statement_files"] = statement_count
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "output_dir": str(output_dir),
        "transactions_parquet": str(output_dir / "transactions.parquet"),
        "statements_dir": str(output_dir / "statements"),
        "manifest": str(output_dir / "manifest.json"),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for synthetic data generation."""
    parser = argparse.ArgumentParser(description="Generate deterministic FinPath synthetic data")
    parser.add_argument("--output-dir", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--end-month", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    dataset = generate_dataset(
        num_users=args.users,
        months=args.months,
        seed=args.seed,
        end_month=args.end_month,
    )
    paths = write_dataset(dataset, args.output_dir)
    summary = dataset.summary()
    print(json.dumps({"summary": summary, "paths": paths}, indent=2))
    return 0


__all__ = [
    "SyntheticDataset",
    "generate_dataset",
    "main",
    "write_dataset",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
