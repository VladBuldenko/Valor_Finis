from app.modules.expenses import repository
from app.modules.expenses.schemas import ExpenseCreate, ExpenseResponse


# Creates a new expense using validated expense data.
# This function exists to keep business logic separate from API and storage layers.
# Parameters:
# - expense_data: validated expense input data.
# Returns:
# - ExpenseResponse object created by the repository.
def create_expense(expense_data: ExpenseCreate) -> ExpenseResponse:
    return repository.create_expense(expense_data)


# Returns all created expenses.
# This function exists to provide a clean service layer between router and repository.
# Parameters:
# - None.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses() -> list[ExpenseResponse]:
    return repository.get_expenses()