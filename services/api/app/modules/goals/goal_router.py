from fastapi import APIRouter, status

from app.modules.goals import goal_service
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


router = APIRouter(
    prefix="/goals",
    tags=["Goals"],
)


# Creates a new financial goal through the API.
# This function exists to expose financial goal creation to mobile and web clients.
# Parameters:
# - goal_data: validated request body containing financial goal details.
# Returns:
# - GoalResponse object with generated id and created_at timestamp.
@router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(goal_data: GoalCreate) -> GoalResponse:
    return goal_service.create_goal(goal_data)


# Returns all financial goals through the API.
# This function exists to expose financial goals to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of GoalResponse objects.
@router.get(
    "",
    response_model=list[GoalResponse],
    status_code=status.HTTP_200_OK,
)
def get_goals() -> list[GoalResponse]:
    return goal_service.get_goals()