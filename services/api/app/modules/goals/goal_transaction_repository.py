from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.goals.goal_transaction_models import GoalTransactionModel


# Calculates a goal's ledger balance from its transaction history.
# This function exists as the single source of truth for "what does the
# ledger say this Goal is worth right now" - opening_balance and
# contribution rows add to the balance, withdrawal rows subtract from it.
# A goal with no transactions has a balance of exactly Decimal("0.00").
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier to sum transactions for.
# - user_id: authenticated user identifier that owns the goal, used as a
#   defense-in-depth filter alongside goal_id.
# Returns:
# - Decimal ledger balance for the goal.
def calculate_ledger_balance(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> Decimal:
    transactions = (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
        )
        .all()
    )

    balance = Decimal("0.00")

    for transaction in transactions:
        if transaction.type == "withdrawal":
            balance -= transaction.amount
        else:
            balance += transaction.amount

    return balance


# Creates and saves a new append-only goal transaction record.
# This function exists to isolate PostgreSQL write operations for the
# ledger from business logic and HTTP handling. It never commits by
# default so the caller (goal_service.create_goal_transaction) can compose
# this insert with the transitional goals.current_amount update in a
# single database transaction.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal this transaction belongs to.
# - user_id: authenticated user identifier that owns the goal.
# - type: one of "opening_balance", "contribution", "withdrawal".
# - amount: always positive; direction is carried by type.
# - description: optional free-text note.
# - commit: whether the repository should commit the transaction
#   immediately. Pass False when composing this write with other changes
#   the caller will commit together.
# Returns:
# - GoalTransactionModel instance saved/flushed in the current transaction.
def create_transaction(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
    type: str,
    amount: Decimal,
    description: Optional[str],
    commit: bool = True,
) -> GoalTransactionModel:
    transaction_model = GoalTransactionModel(
        goal_id=goal_id,
        user_id=user_id,
        type=type,
        amount=amount,
        description=description,
    )

    db_session.add(transaction_model)

    if commit:
        db_session.commit()
        db_session.refresh(transaction_model)
    else:
        db_session.flush()

    return transaction_model


# Returns a goal's full transaction history, newest first.
# This function exists to isolate PostgreSQL read operations for the ledger
# from business logic and HTTP handling. Ordering is deterministic
# (created_at DESC, id DESC) so two transactions written in the same
# instant never come back in an arbitrary order between requests.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier to list transactions for.
# - user_id: authenticated user identifier that owns the goal, used as a
#   defense-in-depth filter alongside goal_id.
# Returns:
# - List of GoalTransactionModel instances, newest first.
def get_transactions_for_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> list[GoalTransactionModel]:
    return (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
        )
        .order_by(
            GoalTransactionModel.created_at.desc(),
            GoalTransactionModel.id.desc(),
        )
        .all()
    )


# Returns every one of a user's goals' ledger balances in a single grouped
# query.
# This function exists so a read path that lists multiple Goals at once
# (GET /goals, Goal Progress analytics) never issues one balance query per
# Goal (VF-016D). A Goal with no transactions simply has no entry in the
# returned mapping - callers must default a missing goal_id to
# Decimal("0.00") themselves, since a goal that was never funded has
# nothing to aggregate.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier to scope the aggregation to.
#   Ownership-safe by construction: another user's transactions can never
#   appear in the result, even for a goal_id that happens to collide only
#   in theory (goal_id is already unique, but filtering by user_id here
#   too matches the ownership-defense-in-depth convention used everywhere
#   else in this module).
# Returns:
# - Dict mapping goal_id to its Decimal ledger balance, for goals that
#   have at least one transaction.
def get_ledger_balances_for_user(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, Decimal]:
    signed_amount = case(
        (GoalTransactionModel.type == "withdrawal", -GoalTransactionModel.amount),
        else_=GoalTransactionModel.amount,
    )

    rows = (
        db_session.query(
            GoalTransactionModel.goal_id,
            func.sum(signed_amount).label("balance"),
        )
        .filter(GoalTransactionModel.user_id == user_id)
        .group_by(GoalTransactionModel.goal_id)
        .all()
    )

    return {goal_id: balance for goal_id, balance in rows}
