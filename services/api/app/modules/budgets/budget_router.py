from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse
from app.modules.budgets.budget_errors import BudgetAlreadyExistsError


router = APIRouter(
    prefix="/budgets",
    tags=["Budgets"],
)


# Creates a new budget through the API.
# This function exists to receive validated HTTP input
# and delegate budget creation to the service layer.
# Parameters:
# - budget_data: validated request body containing budget data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - BudgetResponse containing the saved budget.
# Raises:
# - HTTPException: 409 Conflict when the same budget already exists.
@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_budget(
    budget_data: BudgetCreate,
    db_session: Session = Depends(get_db_session),
) -> BudgetResponse:
    try:
        return budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
        )
    except BudgetAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Budget with this name, period, and start date already exists for this user.",
        ) from error


# Returns budgets through the API.
# This function exists to receive HTTP filtering parameters
# and delegate budget retrieval to the service layer.
# Parameters:
# - user_id: optional query parameter used to filter budgets by owner.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of BudgetResponse objects.
@router.get(
    "",
    response_model=list[BudgetResponse],
    status_code=status.HTTP_200_OK,
)
def get_budgets(
    user_id: Optional[UUID] = Query(
        default=None,
        description="Filter budgets by user identifier.",
    ),
    db_session: Session = Depends(get_db_session),
) -> list[BudgetResponse]:
    return budget_service.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )