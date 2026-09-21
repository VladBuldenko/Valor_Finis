from decimal import Decimal
from typing import Optional
from uuid import UUID

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
