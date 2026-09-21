from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals.goal_errors import GoalInsufficientFundsError
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
)
from app.modules.goals.goal_transaction_schemas import (
    GoalTransactionCreate,
    GoalTransactionResponse,
)


# Builds a GoalResponse from a Goal model and an already-computed
# ledger-derived balance.
# This function exists to make the source of current_amount explicit and
# auditable (VF-016D): every public read path must pass in a balance it
# calculated from goal_transactions, never GoalResponse.model_validate(
# goal_model), which would silently read the transitional
# goals.current_amount column instead - the column this slice makes
# non-authoritative for reads.
# Parameters:
# - goal_model: the Goal database record (name/target_amount/etc. only -
#   its own current_amount attribute is deliberately never read here).
# - current_amount: ledger-derived balance to report for this goal.
# Returns:
# - GoalResponse with current_amount set to the given ledger balance.
def _build_goal_response(
    goal_model: GoalModel,
    current_amount: Decimal,
) -> GoalResponse:
    return GoalResponse(
        id=goal_model.id,
        user_id=goal_model.user_id,
        name=goal_model.name,
        target_amount=goal_model.target_amount,
        current_amount=current_amount,
        currency=goal_model.currency,
        target_date=goal_model.target_date,
        status=goal_model.status,
        created_at=goal_model.created_at,
        updated_at=goal_model.updated_at,
    )


# Creates a new financial goal using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal creation data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the saved database model, with a
#   ledger-derived current_amount (always 0.00 for a brand new goal, since
#   it cannot have any transactions yet - but this still goes through the
#   same authoritative-read calculation as every other Goal response).
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
    user_id: UUID,
) -> GoalResponse:
    goal_model = goal_repository.create_goal(
        db_session=db_session,
        goal_data=goal_data,
        user_id=user_id,
    )

    current_amount = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_model.id,
        user_id=user_id,
    )

    return _build_goal_response(goal_model, current_amount)


# Returns financial goals for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# current_amount is ledger-derived (VF-016D): one bulk grouped query
# fetches every one of the user's goal balances up front, so this never
# issues one balance query per Goal no matter how many goals are returned.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter goals.
# Returns:
# - List of GoalResponse objects, ordered exactly as
#   goal_repository.get_goals returns them (created_at DESC).
def get_goals(
    db_session: Session,
    user_id: UUID,
) -> list[GoalResponse]:
    goal_models = goal_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    balances = goal_transaction_repository.get_ledger_balances_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        _build_goal_response(
            goal_model,
            balances.get(goal_model.id, Decimal("0.00")),
        )
        for goal_model in goal_models
    ]


# Updates an existing financial goal owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer. current_amount in the
# returned response is ledger-derived (VF-016D), even though the
# repository update also still synchronizes the transitional
# goals.current_amount column for compatibility - the response never
# trusts that column directly.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - goal_data: validated partial goal update data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the updated database model, with a
#   ledger-derived current_amount.
def update_goal(
    db_session: Session,
    goal_id: UUID,
    goal_data: GoalUpdate,
    user_id: UUID,
) -> GoalResponse:
    goal_model = goal_repository.update_goal(
        db_session=db_session,
        goal_id=goal_id,
        goal_data=goal_data,
        user_id=user_id,
    )

    current_amount = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    return _build_goal_response(goal_model, current_amount)


# Deletes an existing financial goal owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - None.
def delete_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> None:
    goal_repository.delete_goal(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )


# Creates a contribution or withdrawal transaction for a goal owned by the
# authenticated user, and atomically synchronizes the transitional
# current_amount column to the resulting ledger balance.
# This function exists as the single write path for balance-changing goal
# transactions (VF-016C). The whole operation runs as one database
# transaction:
#   1. lock the owned Goal row (SELECT ... FOR UPDATE) so two concurrent
#      writes never validate against the same stale balance;
#   2. calculate the current ledger balance from goal_transactions;
#   3. for a withdrawal, reject if it would take the balance negative;
#   4. insert the new append-only transaction (not yet committed);
#   5. update goals.current_amount to the new ledger-derived balance;
#   6. commit once.
# goal.current_amount is never incremented/decremented from its previous
# value - it is always recomputed from the ledger, so it cannot drift.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - transaction_data: validated contribution/withdrawal request data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalTransactionResponse for the newly created transaction.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
# - GoalInsufficientFundsError: when a withdrawal exceeds the current balance.
def create_goal_transaction(
    db_session: Session,
    goal_id: UUID,
    transaction_data: GoalTransactionCreate,
    user_id: UUID,
) -> GoalTransactionResponse:
    goal_model = goal_repository.get_goal_by_id_for_update(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    current_balance = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    if (
        transaction_data.type == "withdrawal"
        and transaction_data.amount > current_balance
    ):
        db_session.rollback()
        raise GoalInsufficientFundsError()

    transaction_model = goal_transaction_repository.create_transaction(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
        type=transaction_data.type,
        amount=transaction_data.amount,
        description=transaction_data.description,
        commit=False,
    )

    if transaction_data.type == "withdrawal":
        new_balance = current_balance - transaction_data.amount
    else:
        new_balance = current_balance + transaction_data.amount

    goal_model.current_amount = new_balance

    db_session.commit()
    db_session.refresh(transaction_model)

    return GoalTransactionResponse.model_validate(transaction_model)


# Returns the full transaction history for a goal owned by the
# authenticated user.
# This function exists to enforce ownership before ever touching the
# ledger: another user's Goal must behave as not found, never leaking
# whether it exists.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - List of GoalTransactionResponse objects, newest first.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
def get_goal_transactions(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> list[GoalTransactionResponse]:
    goal_repository.get_goal_by_id(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    transaction_models = goal_transaction_repository.get_transactions_for_goal(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    return [
        GoalTransactionResponse.model_validate(transaction_model)
        for transaction_model in transaction_models
    ]