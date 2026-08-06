from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.goals import goal_service
from app.modules.goals.goal_schemas import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
)


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
# Raises:
# - Domain exceptions propagated to the global exception handlers.
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


# Updates an existing financial goal through the API.
# This function exists to receive partial HTTP update input
# and delegate goal update logic to the service layer.
# Parameters:
# - goal_id: financial goal identifier from the URL path.
# - goal_data: validated partial request body containing updated goal data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - GoalResponse containing the updated financial goal.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.patch(
    "/{goal_id}",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
)
def update_goal(
    goal_id: UUID,
    goal_data: GoalUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> GoalResponse:
    return goal_service.update_goal(
        db_session=db_session,
        goal_id=goal_id,
        goal_data=goal_data,
        user_id=current_user.id,
    )


# Deletes an existing financial goal through the API.
# This function exists to receive authenticated delete requests
# and delegate goal deletion to the service layer.
# Parameters:
# - goal_id: financial goal identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_goal(
    goal_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    goal_service.delete_goal(
        db_session=db_session,
        goal_id=goal_id,
        user_id=current_user.id,
    )