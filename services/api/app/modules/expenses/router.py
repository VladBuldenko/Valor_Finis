from fastapi import APIRouter, status

from app.modules.expenses.schemas import ExpenseCreate, ExpenseResponse
from app.modules.expenses import service


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


# Creates a new expense through the API.
# This function exists to expose expense creation to mobile and web clients.
# Parameters:
# - expense_data: validated request body containing expense details.
# Returns:
# - ExpenseResponse object with generated id and created_at timestamp.
@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(expense_data: ExpenseCreate) -> ExpenseResponse:
    return service.create_expense(expense_data)


# Returns all expenses through the API.
# This function exists to expose expense history to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of ExpenseResponse objects.
@router.get(
    "",
    response_model=list[ExpenseResponse],
    status_code=status.HTTP_200_OK,
)
def get_expenses() -> list[ExpenseResponse]:
    return service.get_expenses()