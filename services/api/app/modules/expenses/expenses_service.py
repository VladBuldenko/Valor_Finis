from sqlalchemy.orm import Session

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Creates a new expense using validated expense data.
# This function exists to keep business logic separate from API and database layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data.
# Returns:
# - ExpenseResponse object created by the repository.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
) -> ExpenseResponse:
    return expenses_repository.create_expense(db_session, expense_data)


# Returns all created expenses.
# This function exists to provide a clean service layer between router and repository.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses(db_session: Session) -> list[ExpenseResponse]:
    return expenses_repository.get_expenses(db_session)