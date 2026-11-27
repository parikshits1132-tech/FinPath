"""Deterministic keyword categorisation and self-transfer detection.

The core stays free of persistence and ORM types: callers pass lightweight
``CategoryRule`` records and receive a ``Classification`` value.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MatchType = Literal["contains", "exact"]
CategoryKind = Literal["income", "expense", "transfer"]

MATCH_TYPES: tuple[MatchType, ...] = ("contains", "exact")

# Conservative phrases that indicate money moved between the user's own
# accounts (or a credit-card bill payment) rather than real cash flow.
TRANSFER_KEYWORDS: tuple[str, ...] = (
    "self transfer",
    "self-transfer",
    "credit card payment",
    "credit card bill",
    "cc payment",
    "cc bill payment",
    "payment to self",
    "transfer to self",
)


@dataclass(frozen=True)
class CategoryRule:
    """A persisted keyword rule flattened with its category kind."""

    id: str
    keyword: str
    match_type: str
    category_id: str
    category_kind: str
    priority: int = 100
    is_active: bool = True


@dataclass(frozen=True)
class Classification:
    """Outcome of applying rules to one transaction description."""

    category_id: str | None
    categorisation_source: Literal["uncategorised", "rule"]
    is_transfer: bool
    matched_rule_id: str | None = None


def normalise_text(value: str) -> str:
    """Case-fold and collapse whitespace for stable keyword matching."""
    return " ".join(value.casefold().split())


def rule_matches(description: str, keyword: str, match_type: str) -> bool:
    """Return whether ``keyword`` matches ``description`` under ``match_type``."""
    if match_type not in MATCH_TYPES:
        raise ValueError(f"Unsupported match_type: {match_type}")
    haystack = normalise_text(description)
    needle = normalise_text(keyword)
    if not needle:
        return False
    if match_type == "exact":
        return haystack == needle
    return needle in haystack


def detect_transfer(description: str) -> bool:
    """Return whether a description looks like an own-account or card payment."""
    text = normalise_text(description)
    return any(keyword in text for keyword in TRANSFER_KEYWORDS)


def find_matching_rule(
    rules: Iterable[CategoryRule], description: str
) -> CategoryRule | None:
    """Return the highest-priority active rule matching ``description``.

    Lower ``priority`` numbers win; ties fall back to the lexicographically
    smallest rule id so results stay deterministic across database runs.
    """
    matching = [
        rule
        for rule in rules
        if rule.is_active
        and rule_matches(description, rule.keyword, rule.match_type)
    ]
    if not matching:
        return None
    matching.sort(key=lambda rule: (rule.priority, rule.id))
    return matching[0]


def classify(description: str, rules: Iterable[CategoryRule]) -> Classification:
    """Apply the first matching rule and flag obvious self-transfers."""
    rule = find_matching_rule(rules, description)
    keyword_transfer = detect_transfer(description)
    if rule is None:
        return Classification(
            category_id=None,
            categorisation_source="uncategorised",
            is_transfer=keyword_transfer,
        )
    return Classification(
        category_id=rule.category_id,
        categorisation_source="rule",
        is_transfer=keyword_transfer or rule.category_kind == "transfer",
        matched_rule_id=rule.id,
    )
