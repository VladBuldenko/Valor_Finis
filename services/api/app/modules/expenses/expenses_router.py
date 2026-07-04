from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(
    expense_data: ExpenseCreate,
    db_session: Session = Depends(get_db_session),
) -> ExpenseResponse:
    """
    Creates a new expense.

    What:
        Handles POST /expenses HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        business logic to the service layer.

    Parameters:
        expense_data: Validated request body for creating an expense.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        ExpenseResponse with the saved expense data.
    """

    return expenses_service.create_expense(
        db_session=db_session,
        expense_data=expense_data,
    )


@router.get(
    "",
    response_model=list[ExpenseResponse],
)
def get_expenses(
    user_id: Optional[UUID] = None,
    db_session: Session = Depends(get_db_session),
) -> list[ExpenseResponse]:
    """
    Returns expenses.

    What:
        Handles GET /expenses HTTP requests.

    Why:
        Keeps HTTP filtering input in the router layer and delegates
        data retrieval to the service layer.

    Parameters:
        user_id: Optional user identifier used to filter expenses.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        List of ExpenseResponse objects.
    """

    return expenses_service.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )