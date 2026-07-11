from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.budgets import budget_service
from app.modules.budgets.budget_errors import BudgetAlreadyExistsError
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


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
# - HTTPException: 409 Conflict when the same budget already exists.
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
    try:
        return budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=current_user.id,
        )
    except BudgetAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Budget with this name, period, and start date already exists for this user.",
        ) from error


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