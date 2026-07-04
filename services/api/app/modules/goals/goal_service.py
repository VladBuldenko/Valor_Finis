from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals import goal_repository
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Creates a new financial goal using validated input data.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal creation data.
# Returns:
# - GoalResponse created from the saved database model.
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
) -> GoalResponse:
    goal_model = goal_repository.create_goal(
        db_session=db_session,
        goal_data=goal_data,
    )

    return GoalResponse.model_validate(goal_model)


# Returns financial goals for a user or all goals when user_id is not provided.
# This function exists to map database models to public API responses
# and provide a place for future business rules.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter goals.
# Returns:
# - List of GoalResponse objects.
def get_goals(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[GoalResponse]:
    goal_models = goal_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        GoalResponse.model_validate(goal_model)
        for goal_model in goal_models
    ]