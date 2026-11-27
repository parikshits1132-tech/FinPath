"""Category, keyword-rule, and retroactive categorisation services."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from finpath_core.categorisation import (
    CategoryRule,
    Classification,
    classify,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CategorisationRule,
    FinancialTransaction,
    TransactionCategory,
)
from app.schemas.categories import (
    ApplyRulesResult,
    CategoryCreate,
    CategoryKind,
    CategoryUpdate,
    MatchType,
    RuleCreate,
    RuleRead,
    RuleUpdate,
)


class CategoryConflictError(Exception):
    """Raised when a category name/kind clashes with an existing category."""


class SystemCategoryProtectedError(Exception):
    """Raised when a caller tries to rename or delete a system category."""


class UnknownCategoryError(Exception):
    """Raised when a referenced category is not visible to the user."""


async def list_categories(
    session: AsyncSession, user_id: UUID, *, kind: str | None = None
) -> list[TransactionCategory]:
    """Return system categories plus the user's own categories."""
    stmt = select(TransactionCategory).where(
        (TransactionCategory.user_id.is_(None)) | (TransactionCategory.user_id == user_id)
    )
    if kind is not None:
        stmt = stmt.where(TransactionCategory.kind == kind)
    stmt = stmt.order_by(
        TransactionCategory.is_system.desc(),
        TransactionCategory.kind,
        TransactionCategory.name,
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_category(
    session: AsyncSession, user_id: UUID, category_id: UUID
) -> TransactionCategory | None:
    """Fetch a system or user-owned category by id."""
    return (
        await session.execute(
            select(TransactionCategory).where(
                TransactionCategory.id == category_id,
                (TransactionCategory.user_id.is_(None))
                | (TransactionCategory.user_id == user_id),
            )
        )
    ).scalar_one_or_none()


async def create_category(
    session: AsyncSession, user_id: UUID, payload: CategoryCreate
) -> TransactionCategory:
    """Create a user-defined category."""
    if payload.parent_id is not None:
        parent = await get_category(session, user_id, payload.parent_id)
        if parent is None:
            raise UnknownCategoryError(str(payload.parent_id))
    category = TransactionCategory(
        user_id=user_id,
        parent_id=payload.parent_id,
        name=payload.name.strip(),
        kind=payload.kind,
        is_system=False,
    )
    session.add(category)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise CategoryConflictError from exc
    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession, user_id: UUID, category_id: UUID, payload: CategoryUpdate
) -> TransactionCategory | None:
    """Rename or re-parent a user-defined category."""
    category = await get_category(session, user_id, category_id)
    if category is None:
        return None
    if category.is_system or category.user_id != user_id:
        raise SystemCategoryProtectedError
    changes = payload.model_dump(exclude_unset=True)
    if "parent_id" in changes and changes["parent_id"] is not None:
        if changes["parent_id"] == category.id:
            raise CategoryConflictError
        parent = await get_category(session, user_id, changes["parent_id"])
        if parent is None:
            raise UnknownCategoryError(str(changes["parent_id"]))
    if "name" in changes and changes["name"] is not None:
        changes["name"] = str(changes["name"]).strip()
    for field_name, value in changes.items():
        setattr(category, field_name, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise CategoryConflictError from exc
    await session.refresh(category)
    return category


async def delete_category(
    session: AsyncSession, user_id: UUID, category_id: UUID
) -> bool:
    """Delete a user-defined category; transactions keep null categorisation."""
    category = await get_category(session, user_id, category_id)
    if category is None:
        return False
    if category.is_system or category.user_id != user_id:
        raise SystemCategoryProtectedError
    await session.delete(category)
    await session.flush()
    return True


def _to_rule_read(rule: CategorisationRule, category: TransactionCategory) -> RuleRead:
    return RuleRead(
        id=rule.id,
        keyword=rule.keyword,
        match_type=cast(MatchType, rule.match_type),
        category_id=rule.category_id,
        category_name=category.name,
        category_kind=cast(CategoryKind, category.kind),
        priority=rule.priority,
        is_active=rule.is_active,
        created_at=rule.created_at,
    )


async def list_rules(session: AsyncSession, user_id: UUID) -> list[RuleRead]:
    """Return the user's rules ordered by evaluation priority."""
    rows = (
        await session.execute(
            select(CategorisationRule, TransactionCategory)
            .join(
                TransactionCategory,
                TransactionCategory.id == CategorisationRule.category_id,
            )
            .where(CategorisationRule.user_id == user_id)
            .order_by(CategorisationRule.priority, CategorisationRule.created_at)
        )
    ).all()
    return [_to_rule_read(rule, category) for rule, category in rows]


async def _get_rule(
    session: AsyncSession, user_id: UUID, rule_id: UUID
) -> tuple[CategorisationRule, TransactionCategory] | None:
    row = (
        await session.execute(
            select(CategorisationRule, TransactionCategory)
            .join(
                TransactionCategory,
                TransactionCategory.id == CategorisationRule.category_id,
            )
            .where(
                CategorisationRule.id == rule_id,
                CategorisationRule.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


async def create_rule(
    session: AsyncSession, user_id: UUID, payload: RuleCreate
) -> RuleRead:
    """Create a keyword rule and re-apply rules to existing transactions."""
    category = await get_category(session, user_id, payload.category_id)
    if category is None:
        raise UnknownCategoryError(str(payload.category_id))
    rule = CategorisationRule(
        user_id=user_id,
        keyword=payload.keyword.strip(),
        match_type=payload.match_type,
        category_id=payload.category_id,
        priority=payload.priority,
        is_active=payload.is_active,
    )
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    await apply_rules(session, user_id)
    return _to_rule_read(rule, category)


async def update_rule(
    session: AsyncSession, user_id: UUID, rule_id: UUID, payload: RuleUpdate
) -> RuleRead | None:
    """Update a rule and re-apply rules to existing transactions."""
    existing = await _get_rule(session, user_id, rule_id)
    if existing is None:
        return None
    rule, current_category = existing
    changes = payload.model_dump(exclude_unset=True)
    if "category_id" in changes and changes["category_id"] is not None:
        category = await get_category(session, user_id, changes["category_id"])
        if category is None:
            raise UnknownCategoryError(str(changes["category_id"]))
    else:
        category = current_category
    if "keyword" in changes and changes["keyword"] is not None:
        changes["keyword"] = str(changes["keyword"]).strip()
    for field_name, value in changes.items():
        setattr(rule, field_name, value)
    await session.flush()
    await session.refresh(rule)
    await apply_rules(session, user_id)
    return _to_rule_read(rule, category)


async def delete_rule(session: AsyncSession, user_id: UUID, rule_id: UUID) -> bool:
    """Delete a rule; existing categorisations remain until re-applied."""
    rule = (
        await session.execute(
            select(CategorisationRule).where(
                CategorisationRule.id == rule_id,
                CategorisationRule.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        return False
    await session.delete(rule)
    await session.flush()
    return True


async def load_rules(session: AsyncSession, user_id: UUID) -> list[CategoryRule]:
    """Load rules with category metadata for the pure classifier."""
    rows = (
        await session.execute(
            select(CategorisationRule, TransactionCategory)
            .join(
                TransactionCategory,
                TransactionCategory.id == CategorisationRule.category_id,
            )
            .where(CategorisationRule.user_id == user_id)
        )
    ).all()
    return [
        CategoryRule(
            id=str(rule.id),
            keyword=rule.keyword,
            match_type=rule.match_type,
            category_id=str(rule.category_id),
            category_kind=category.kind,
            priority=rule.priority,
            is_active=rule.is_active,
        )
        for rule, category in rows
    ]


def classify_transaction(
    description_clean: str, rules: list[CategoryRule]
) -> Classification:
    """Classify one description using the pure core implementation."""
    return classify(description_clean, rules)


async def apply_rules(session: AsyncSession, user_id: UUID) -> ApplyRulesResult:
    """Re-run rules over non-manual transactions, preserving manual choices."""
    rules = await load_rules(session, user_id)
    transactions = (
        await session.execute(
            select(FinancialTransaction).where(
                FinancialTransaction.user_id == user_id,
                FinancialTransaction.categorisation_source != "manual",
            )
        )
    ).scalars().all()

    updated = 0
    flagged = 0
    for transaction in transactions:
        classification = classify(transaction.description_clean, rules)
        category_id = (
            UUID(classification.category_id) if classification.category_id else None
        )
        changed = (
            transaction.category_id != category_id
            or transaction.categorisation_source != classification.categorisation_source
            or transaction.is_transfer != classification.is_transfer
        )
        if changed:
            transaction.category_id = category_id
            transaction.categorisation_source = classification.categorisation_source
            transaction.is_transfer = classification.is_transfer
            updated += 1
            if classification.is_transfer:
                flagged += 1

    await session.flush()
    return ApplyRulesResult(
        scanned_transactions=len(transactions),
        updated_transactions=updated,
        flagged_transfers=flagged,
    )
