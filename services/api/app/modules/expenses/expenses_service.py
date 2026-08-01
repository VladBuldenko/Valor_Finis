from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_schemas import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
)


# Creates a new expense using validated expense data and authenticated user id.
# This function exists to keep business logic separate
# from API and database layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data.
# - user_id: authenticated user identifier that owns the expense.
# - commit: whether the expense should be committed immediately.
# Returns:
# - ExpenseResponse object created from the saved database model.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
    user_id: UUID,
    commit: bool = True,
) -> ExpenseResponse:
    expense_model = expenses_repository.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
        commit=commit,
    )

    return ExpenseResponse.model_validate(expense_model)


# Returns expenses for the authenticated user.
# This function exists to keep response mapping outside the repository layer
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses(
    db_session: Session,
    user_id: UUID,
) -> list[ExpenseResponse]:
    expense_models = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        ExpenseResponse.model_validate(expense_model)
        for expense_model in expense_models
    ]


# Updates an existing expense owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - expense_data: validated partial expense update data.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseResponse object created from the updated database model.
def update_expense(
    db_session: Session,
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    user_id: UUID,
) -> ExpenseResponse:
    expense_model = expenses_repository.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=user_id,
    )

    return ExpenseResponse.model_validate(expense_model)


# Deletes an existing expense owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - None.
def delete_expense(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> None:
    expenses_repository.delete_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )