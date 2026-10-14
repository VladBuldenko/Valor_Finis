from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
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
# - priority_rank: the rank computed by the service under the user lock L0
#   (None for an archived Goal).
# - commit: whether to commit immediately. The Goal write path passes False:
#   the service owns the transaction so L0 and the row locks are held until
#   its single commit (VF-020D3).
# Returns:
# - GoalModel instance saved (flushed, and committed when commit is True).
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
    user_id: UUID,
    priority_rank: Optional[int] = None,
    commit: bool = True,
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
        priority_rank=priority_rank,
    )

    db_session.add(goal_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(goal_model)

    return goal_model


# Returns the financial goal database records of one user.
# This function exists to isolate PostgreSQL read operations
# from business logic and HTTP handling. The user scope is mandatory
# (VF-020B1): there is no "all users" query path, so a caller can never
# read another user's goals by omitting the user id.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier whose goals are returned.
# Returns:
# - List of the user's GoalModel instances in the canonical order
#   (VF-020D, P74): (1) non-archived ranked Goals by priority_rank ASC,
#   (2) non-archived Goals with a NULL rank (rollout stragglers) by
#   created_at ASC, id ASC, (3) archived Goals by created_at DESC, id ASC.
def get_goals(
    db_session: Session,
    user_id: UUID,
) -> list[GoalModel]:
    order_group = case(
        (GoalModel.status == "archived", 2),
        (GoalModel.priority_rank.is_(None), 1),
        else_=0,
    )
    straggler_created_at = case((order_group == 1, GoalModel.created_at))
    archived_created_at = case((order_group == 2, GoalModel.created_at))

    return (
        db_session.query(GoalModel)
        .filter(GoalModel.user_id == user_id)
        .order_by(
            order_group.asc(),
            GoalModel.priority_rank.asc().nulls_last(),
            straggler_created_at.asc().nulls_last(),
            archived_created_at.desc().nulls_last(),
            GoalModel.id.asc(),
        )
        .all()
    )


# Returns the highest assigned rank of a user's Goals, or 0 when none is
# ranked. Callers hold the user lock L0, so the value cannot change before
# their commit. Only non-NULL ranks count; gaps are not compacted.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier.
# Returns:
# - COALESCE(MAX(priority_rank), 0).
def get_max_priority_rank(
    db_session: Session,
    user_id: UUID,
) -> int:
    value = (
        db_session.query(func.coalesce(func.max(GoalModel.priority_rank), 0))
        .filter(GoalModel.user_id == user_id)
        .scalar()
    )

    return int(value)


# Returns ALL of a user's Goals (archived included), locking every row with
# SELECT ... FOR UPDATE in ascending id order. Used by the priority reorder
# under L0 so concurrent Goal writers of the same user are fully serialized
# and the set is validated against a locked snapshot.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier.
# Returns:
# - The user's GoalModel instances ordered by id ASC.
def get_all_goals_for_update(
    db_session: Session,
    user_id: UUID,
) -> list[GoalModel]:
    return (
        db_session.query(GoalModel)
        .filter(GoalModel.user_id == user_id)
        .order_by(GoalModel.id.asc())
        .with_for_update()
        .all()
    )


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
# - commit: False when the service owns the transaction (VF-020D3).
# Returns:
# - Updated GoalModel instance.
def apply_goal_update(
    db_session: Session,
    goal_model: GoalModel,
    goal_data: GoalUpdate,
    commit: bool = True,
) -> GoalModel:
    update_data = goal_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(goal_model, field_name, field_value)

    # No balance-vs-target_amount check here (VF-016): overfunding is an
    # allowed product state, so changing target_amount below the Goal's
    # ledger-derived balance is always valid. The Goal row has no balance
    # field to compare against in the first place (VF-016G).
    #
    # commit=False (VF-020D3): the service owns the transaction so the user
    # lock L0 and the Goal row lock stay held until its single commit; the
    # changes are only flushed here.
    if commit:
        db_session.commit()
    else:
        db_session.flush()

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
    commit: bool = True,
) -> None:
    db_session.delete(goal_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()