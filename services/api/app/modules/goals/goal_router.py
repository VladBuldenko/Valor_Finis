from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.goals import goal_service
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


router = APIRouter(
    prefix="/goals",
    tags=["Goals"],
)


# Creates a new financial goal through the API.
# This function exists to receive validated HTTP input
# and delegate goal creation to the service layer.
# Parameters:
# - goal_data: validated request body containing financial goal data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - GoalResponse containing the saved financial goal.
@router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(
    goal_data: GoalCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> GoalResponse:
    return goal_service.create_goal(
        db_session=db_session,
        goal_data=goal_data,
        user_id=current_user.id,
    )


# Returns financial goals through the API.
# This function exists to receive authenticated HTTP requests
# and delegate goal retrieval to the service layer.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of GoalResponse objects that belong to the authenticated user.
@router.get(
    "",
    response_model=list[GoalResponse],
    status_code=status.HTTP_200_OK,
)
def get_goals(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[GoalResponse]:
    return goal_service.get_goals(
        db_session=db_session,
        user_id=current_user.id,
    )