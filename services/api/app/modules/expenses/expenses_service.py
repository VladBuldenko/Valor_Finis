from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Creates a new expense using validated expense data and authenticated user id.
# This function exists to keep business logic separate from API and database layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseResponse object created from the saved database model.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
    user_id: UUID,
) -> ExpenseResponse:
    expense_model = expenses_repository.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
    )

    return ExpenseResponse.model_validate(expense_model)


# Returns expenses for a user or all expenses if user_id is not provided.
# This function exists to keep response mapping outside the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter expenses.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[ExpenseResponse]:
    expense_models = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        ExpenseResponse.model_validate(expense_model)
        for expense_model in expense_models
    ]