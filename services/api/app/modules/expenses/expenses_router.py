from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
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
    current_user: CurrentUser = Depends(get_current_user),
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
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        ExpenseResponse with the saved expense data.
    """

    return expenses_service.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=current_user.id,
    )


@router.get(
    "",
    response_model=list[ExpenseResponse],
)
def get_expenses(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[ExpenseResponse]:
    """
    Returns expenses for the authenticated user.

    What:
        Handles GET /expenses HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        data retrieval to the service layer.

    Parameters:
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        List of ExpenseResponse objects that belong to the authenticated user.
    """

    return expenses_service.get_expenses(
        db_session=db_session,
        user_id=current_user.id,
    )