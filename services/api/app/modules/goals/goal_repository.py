from sqlalchemy.orm import Session

from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Creates a new financial goal record in PostgreSQL.
# This function exists to isolate database write logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal input data from the service layer.
# Returns:
# - GoalResponse object created from the saved database model.
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
) -> GoalResponse:
    goal_model = GoalModel(
        name=goal_data.name,
        target_amount=goal_data.target_amount,
        current_amount=goal_data.current_amount,
        deadline=goal_data.deadline,
    )

    db_session.add(goal_model)
    db_session.commit()
    db_session.refresh(goal_model)

    return GoalResponse.model_validate(goal_model)


# Returns all financial goal records from PostgreSQL.
# This function exists to isolate database read logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of GoalResponse objects created from database models.
def get_goals(db_session: Session) -> list[GoalResponse]:
    goal_models = db_session.query(GoalModel).all()

    return [
        GoalResponse.model_validate(goal_model)
        for goal_model in goal_models
    ]