from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals.goal_errors import GoalNotFoundError
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate


# Creates and saves a new financial goal database record.
# This function exists to isolate PostgreSQL write operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal creation data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalModel instance saved in PostgreSQL.
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
    user_id: UUID,
) -> GoalModel:
    # A new Goal has no goal_transactions rows yet, so its ledger-derived
    # balance is Decimal("0.00") by construction (VF-016G) - there is no
    # balance field to set here at all.
    goal_model = GoalModel(
        user_id=user_id,
        name=goal_data.name,
        target_amount=goal_data.target_amount,
        currency=goal_data.currency,
        target_date=goal_data.target_date,
        status=goal_data.status,
    )

    db_session.add(goal_model)
    db_session.commit()
    db_session.refresh(goal_model)

    return goal_model


# Returns financial goal database records.
# This function exists to isolate PostgreSQL read operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter goals.
# Returns:
# - List of GoalModel instances from the database.
def get_goals(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[GoalModel]:
    query = db_session.query(GoalModel)

    if user_id is not None:
        query = query.filter(GoalModel.user_id == user_id)

    return query.order_by(GoalModel.created_at.desc()).all()


# Returns one financial goal by goal id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalModel instance from the database.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
def get_goal_by_id(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> GoalModel:
    goal_model = (
        db_session.query(GoalModel)
        .filter(
            GoalModel.id == goal_id,
            GoalModel.user_id == user_id,
        )
        .first()
    )

    if goal_model is None:
        raise GoalNotFoundError()

    return goal_model


# Returns one financial goal by goal id and authenticated user id, locking
# the row with SELECT ... FOR UPDATE for the duration of the caller's
# transaction.
# This function exists so every balance-changing write (contribution/
# withdrawal) reads the Goal under a row lock before calculating the ledger
# balance, closing the race where two concurrent withdrawals could both
# validate against the same stale balance. Callers must not commit or
# release the session between this call and the balance-changing write it
# guards.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalModel instance from the database, locked for update.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
def get_goal_by_id_for_update(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> GoalModel:
    goal_model = (
        db_session.query(GoalModel)
        .filter(
            GoalModel.id == goal_id,
            GoalModel.user_id == user_id,
        )
        .with_for_update()
        .first()
    )

    if goal_model is None:
        raise GoalNotFoundError()

    return goal_model


# Applies validated partial update data to an already-locked Goal model
# and commits.
# This function exists to isolate PostgreSQL update operations from
# business logic and HTTP handling. Callers (goal_service.update_goal)
# must have already obtained the row lock via get_goal_by_id_for_update
# and performed any business-rule checks (e.g. currency immutability,
# VF-016E) before calling this - it applies changes unconditionally and
# never re-checks ownership or business rules itself.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_model: the already-locked GoalModel instance to update.
# - goal_data: validated partial goal update data.
# Returns:
# - Updated GoalModel instance.
def apply_goal_update(
    db_session: Session,
    goal_model: GoalModel,
    goal_data: GoalUpdate,
) -> GoalModel:
    update_data = goal_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(goal_model, field_name, field_value)

    # No balance-vs-target_amount check here (VF-016): overfunding is an
    # allowed product state, so changing target_amount below the Goal's
    # ledger-derived balance is always valid. The Goal row has no balance
    # field to compare against in the first place (VF-016G).
    db_session.commit()
    db_session.refresh(goal_model)

    return goal_model


# Deletes an already-locked Goal model and commits.
# This function exists to isolate PostgreSQL delete operations from
# business logic and HTTP handling. Callers (goal_service.delete_goal)
# must have already obtained the row lock via get_goal_by_id_for_update
# and confirmed no transaction history exists (VF-016E) before calling
# this - it deletes unconditionally and never re-checks ownership or
# transaction history itself. The FK RESTRICT on
# goal_transactions.goal_id remains as defense-in-depth if that check is
# ever bypassed.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_model: the already-locked GoalModel instance to delete.
# Returns:
# - None.
def delete_locked_goal(
    db_session: Session,
    goal_model: GoalModel,
) -> None:
    db_session.delete(goal_model)
    db_session.commit()