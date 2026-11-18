from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.future_obligations.future_obligation_errors import (
    FutureObligationLinkUniqueViolationError,
)
from app.modules.future_obligations.future_obligation_link_models import (
    UNIQUE_EXPENSE_CONSTRAINT,
    UNIQUE_OCCURRENCE_CONSTRAINT,
    FutureObligationExpenseLinkModel as Link,
)

# Persistence for the occurrence <-> Expense links (VF-GOALS-PLANNING-002C2). Every
# function is scoped to the owner. Nothing here writes an Expense, an Account or an
# obligation: a link is relationship metadata only.

CANDIDATE_BUCKETS = ("different_currency", "different_amount", "already_linked", "dated_in_future")


# Inserts a link. The caller holds the Expense and obligation row locks and
# commits. Raises FutureObligationLinkUniqueViolationError (naming the rule) when
# a unique constraint is violated, so a concurrent conflict is never a 500.
def create_link(
    db_session: Session,
    user_id: UUID,
    obligation_id: UUID,
    due_date: date,
    expense_id: UUID,
) -> Link:
    link = Link(user_id=user_id, obligation_id=obligation_id, due_date=due_date, expense_id=expense_id)

    db_session.add(link)

    try:
        db_session.flush()
    except IntegrityError as error:
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)

        if constraint_name in (UNIQUE_EXPENSE_CONSTRAINT, UNIQUE_OCCURRENCE_CONSTRAINT):
            raise FutureObligationLinkUniqueViolationError(constraint_name) from error

        raise

    db_session.refresh(link)

    return link


# One link of the user, or None (a foreign link is None too).
def get_by_id(db_session: Session, link_id: UUID, user_id: UUID, for_update: bool = False) -> Optional[Link]:
    query = db_session.query(Link).filter(Link.id == link_id, Link.user_id == user_id)

    if for_update:
        query = query.with_for_update()

    return query.first()


# The link of one occurrence, or None.
def get_by_occurrence(
    db_session: Session,
    user_id: UUID,
    obligation_id: UUID,
    due_date: date,
) -> Optional[Link]:
    return (
        db_session.query(Link)
        .filter(
            Link.user_id == user_id,
            Link.obligation_id == obligation_id,
            Link.due_date == due_date,
        )
        .first()
    )


# The link of one Expense, or None.
def get_by_expense(db_session: Session, user_id: UUID, expense_id: UUID) -> Optional[Link]:
    return (
        db_session.query(Link)
        .filter(Link.user_id == user_id, Link.expense_id == expense_id)
        .first()
    )


# Every link of one obligation (bounded by the obligation's occurrences).
def list_for_obligation(db_session: Session, user_id: UUID, obligation_id: UUID) -> list[Link]:
    return (
        db_session.query(Link)
        .filter(Link.user_id == user_id, Link.obligation_id == obligation_id)
        .order_by(Link.due_date.asc())
        .all()
    )


def delete_link(db_session: Session, link: Link) -> None:
    db_session.delete(link)
    db_session.flush()


# The user's links whose due date falls in [start, end], with the linked Expense,
# in one query. Used by the overview.
def list_in_window_with_expenses(
    db_session: Session,
    user_id: UUID,
    start: date,
    end: date,
) -> list[tuple[Link, ExpenseModel]]:
    return (
        db_session.query(Link, ExpenseModel)
        .join(ExpenseModel, ExpenseModel.id == Link.expense_id)
        .filter(
            Link.user_id == user_id,
            Link.due_date >= start,
            Link.due_date <= end,
        )
        .all()
    )


# The Expenses that can be linked to an occurrence of `amount` in `currency`: same
# currency, exactly the same amount, no link yet, recorded on or before `as_of`.
# Newest first, bounded by `limit`.
def list_candidate_expenses(
    db_session: Session,
    user_id: UUID,
    currency: str,
    amount: Decimal,
    as_of: date,
    limit: int,
) -> list[ExpenseModel]:
    return (
        db_session.query(ExpenseModel)
        .outerjoin(Link, Link.expense_id == ExpenseModel.id)
        .filter(
            ExpenseModel.user_id == user_id,
            ExpenseModel.currency == currency,
            ExpenseModel.amount == amount,
            ExpenseModel.expense_date <= as_of,
            Link.id.is_(None),
        )
        .order_by(ExpenseModel.expense_date.desc(), ExpenseModel.created_at.desc(), ExpenseModel.id.asc())
        .limit(limit)
        .all()
    )


# Counts the user's Expenses that cannot be linked, by the FIRST reason that
# applies (currency, then amount, then already linked, then dated in the future).
# One grouped query. Expenses that can be linked are not counted here.
def count_excluded_expenses(
    db_session: Session,
    user_id: UUID,
    currency: str,
    amount: Decimal,
    as_of: date,
) -> dict[str, int]:
    bucket = case(
        (ExpenseModel.currency != currency, "different_currency"),
        (ExpenseModel.amount != amount, "different_amount"),
        (Link.id.is_not(None), "already_linked"),
        (ExpenseModel.expense_date > as_of, "dated_in_future"),
        else_="candidate",
    )

    rows = (
        db_session.query(bucket, func.count(ExpenseModel.id))
        .select_from(ExpenseModel)
        .outerjoin(Link, Link.expense_id == ExpenseModel.id)
        .filter(ExpenseModel.user_id == user_id)
        .group_by(bucket)
        .all()
    )

    counts = {name: 0 for name in CANDIDATE_BUCKETS}

    for name, count in rows:
        if name in counts:
            counts[name] = int(count)

    return counts
