from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals import goal_repository
from app.modules.goals.goal_schemas import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
)


# Creates a new financial goal using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal creation data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the saved database model.
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

    return GoalResponse.model_validate(goal_model)


# Returns financial goals for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter goals.
# Returns:
# - List of GoalResponse objects.
def get_goals(
    db_session: Session,
    user_id: UUID,
) -> list[GoalResponse]:
    goal_models = goal_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        GoalResponse.model_validate(goal_model)
        for goal_model in goal_models
    ]


# Updates an existing financial goal owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - goal_data: validated partial goal update data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the updated database model.
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

    return GoalResponse.model_validate(goal_model)


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