from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


# Creates a new expense through the API.
# This function exists to expose expense creation to mobile and web clients.
# Parameters:
# - expense_data: validated request body containing expense details.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - ExpenseResponse object with generated id and created_at timestamp.
@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(
    expense_data: ExpenseCreate,
    db_session: Session = Depends(get_db_session),
) -> ExpenseResponse:
    return expenses_service.create_expense(db_session, expense_data)


# Returns all expenses through the API.
# This function exists to expose expense history to mobile and web clients.
# Parameters:
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - List of ExpenseResponse objects.
@router.get(
    "",
    response_model=list[ExpenseResponse],
    status_code=status.HTTP_200_OK,
)
def get_expenses(
    db_session: Session = Depends(get_db_session),
) -> list[ExpenseResponse]:
    return expenses_service.get_expenses(db_session)