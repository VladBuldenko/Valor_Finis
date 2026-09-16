from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.budgets.budget_version_models import BudgetVersionModel


# Creates and saves a new budget version record.
# This function exists to isolate PostgreSQL write operations for
# append-only budget history from business logic in the service layer.
# Never UPSERTs: two edits within the same period produce two rows, so the
# audit trail is never lost.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget this version belongs to.
# - user_id: authenticated user identifier that owns the budget.
# - effective_from: first period start this version applies to.
# - effective_until: last period end this version applies to, or None for
#   open-ended.
# - limit_amount: the limit in effect from effective_from.
# - category_id: the category scope in effect from effective_from.
# - change_reason: one of "initial", "user_edit", "category_change".
# - commit: whether the repository should commit the transaction immediately.
#   Pass False when the service layer is writing this version alongside a
#   budget row change and will commit both together.
# Returns:
# - BudgetVersionModel instance saved or flushed in the current transaction.
def create_version(
    db_session: Session,
    budget_id: UUID,
    user_id: UUID,
    effective_from: date,
    effective_until: Optional[date],
    limit_amount: Decimal,
    category_id: Optional[UUID],
    change_reason: str,
    commit: bool = True,
) -> BudgetVersionModel:
    version_model = BudgetVersionModel(
        budget_id=budget_id,
        user_id=user_id,
        effective_from=effective_from,
        effective_until=effective_until,
        limit_amount=limit_amount,
        category_id=category_id,
        change_reason=change_reason,
    )

    db_session.add(version_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(version_model)

    return version_model


# Deletes every version row for a budget.
# This function exists for the narrow pre-first-period edit path: a
# period/start_date correction (only reachable before the budget's first
# period has completed) redefines what the "initial" version means, and at
# that point no real period has been locked in yet, so replacing the whole
# history is safe rather than appending to it.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget whose version rows are being replaced.
# - commit: whether the repository should commit the transaction immediately.
#   Pass False when the service layer is also writing a replacement version
#   and will commit both together.
# Returns:
# - None.
def delete_versions_for_budget(
    db_session: Session,
    budget_id: UUID,
    commit: bool = True,
) -> None:
    db_session.query(BudgetVersionModel).filter(
        BudgetVersionModel.budget_id == budget_id,
    ).delete()

    if commit:
        db_session.commit()
    else:
        db_session.flush()


# Resolves the version that was in effect for a given period.
# This function exists to answer "what limit/category configuration applied
# to this budget at period X," which is the entire reason budget_versions
# exists. Selects the version with the greatest effective_from that is
# still <= period_start and whose effective_until (if any) covers
# period_end, tie-broken by the most recently created row.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget to resolve a version for.
# - period_start: inclusive start of the period being resolved.
# - period_end: inclusive end of the period being resolved.
# Returns:
# - The matching BudgetVersionModel, or None if no version covers this period.
def resolve_version_for_period(
    db_session: Session,
    budget_id: UUID,
    period_start: date,
    period_end: date,
) -> Optional[BudgetVersionModel]:
    return (
        db_session.query(BudgetVersionModel)
        .filter(
            BudgetVersionModel.budget_id == budget_id,
            BudgetVersionModel.effective_from <= period_start,
            or_(
                BudgetVersionModel.effective_until.is_(None),
                BudgetVersionModel.effective_until >= period_end,
            ),
        )
        .order_by(
            BudgetVersionModel.effective_from.desc(),
            BudgetVersionModel.created_at.desc(),
            BudgetVersionModel.id.desc(),
        )
        .first()
    )
