from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals.goal_errors import GoalInvalidAmountError, GoalNotFoundError
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
    goal_model = GoalModel(
        user_id=user_id,
        name=goal_data.name,
        target_amount=goal_data.target_amount,
        current_amount=goal_data.current_amount,
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


# Updates an existing financial goal owned by the authenticated user.
# This function exists to isolate PostgreSQL update operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - goal_data: validated partial goal update data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - Updated GoalModel instance.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
# - GoalInvalidAmountError: when current_amount becomes greater than target_amount.
def update_goal(
    db_session: Session,
    goal_id: UUID,
    goal_data: GoalUpdate,
    user_id: UUID,
) -> GoalModel:
    goal_model = get_goal_by_id(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    update_data = goal_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(goal_model, field_name, field_value)

    if goal_model.current_amount > goal_model.target_amount:
        db_session.rollback()
        raise GoalInvalidAmountError()

    db_session.commit()
    db_session.refresh(goal_model)

    return goal_model


# Deletes an existing financial goal owned by the authenticated user.
# This function exists to isolate PostgreSQL delete operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - None.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
def delete_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> None:
    goal_model = get_goal_by_id(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    db_session.delete(goal_model)
    db_session.commit()