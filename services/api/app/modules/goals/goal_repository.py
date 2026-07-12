from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate


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