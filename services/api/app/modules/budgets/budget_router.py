from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
)


router = APIRouter(
    prefix="/budgets",
    tags=["Budgets"],
)


# Creates a new budget through the API.
# This function exists to receive validated HTTP input
# and delegate budget creation to the service layer.
# Parameters:
# - budget_data: validated request body containing budget data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - BudgetResponse containing the saved budget.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_budget(
    budget_data: BudgetCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> BudgetResponse:
    return budget_service.create_budget(
        db_session=db_session,
        budget_data=budget_data,
        user_id=current_user.id,
    )


# Returns budgets through the API.
# This function exists to receive authenticated HTTP requests
# and delegate budget retrieval to the service layer.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of BudgetResponse objects that belong to the authenticated user.
@router.get(
    "",
    response_model=list[BudgetResponse],
    status_code=status.HTTP_200_OK,
)
def get_budgets(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[BudgetResponse]:
    return budget_service.get_budgets(
        db_session=db_session,
        user_id=current_user.id,
    )


# Updates an existing budget through the API.
# This function exists to receive partial HTTP update input
# and delegate budget update logic to the service layer.
# Parameters:
# - budget_id: budget identifier from the URL path.
# - budget_data: validated partial request body containing updated budget data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - BudgetResponse containing the updated budget.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.patch(
    "/{budget_id}",
    response_model=BudgetResponse,
    status_code=status.HTTP_200_OK,
)
def update_budget(
    budget_id: UUID,
    budget_data: BudgetUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> BudgetResponse:
    return budget_service.update_budget(
        db_session=db_session,
        budget_id=budget_id,
        budget_data=budget_data,
        user_id=current_user.id,
    )


# Deletes an existing budget through the API.
# This function exists to receive authenticated delete requests
# and delegate budget deletion to the service layer.
# Parameters:
# - budget_id: budget identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_budget(
    budget_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    budget_service.delete_budget(
        db_session=db_session,
        budget_id=budget_id,
        user_id=current_user.id,
    )