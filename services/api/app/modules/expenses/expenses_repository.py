from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseUpdate


# Creates a new expense database record.
# This function exists to isolate PostgreSQL write logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data from the service layer.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseModel instance saved in the database.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
    user_id: UUID,
) -> ExpenseModel:
    expense_model = ExpenseModel(
        user_id=user_id,
        category_id=expense_data.category_id,
        title=expense_data.title,
        amount=expense_data.amount,
        currency=expense_data.currency,
        expense_date=expense_data.expense_date,
        description=expense_data.description,
        source=expense_data.source,
    )

    db_session.add(expense_model)
    db_session.commit()
    db_session.refresh(expense_model)

    return expense_model


# Returns expense database records.
# This function exists to isolate PostgreSQL read logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter expenses.
# Returns:
# - List of ExpenseModel instances from the database.
def get_expenses(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[ExpenseModel]:
    query = db_session.query(ExpenseModel)

    if user_id is not None:
        query = query.filter(ExpenseModel.user_id == user_id)

    return query.order_by(ExpenseModel.expense_date.desc()).all()


# Returns one expense by expense id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseModel instance from the database.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def get_expense_by_id(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> ExpenseModel:
    expense_model = (
        db_session.query(ExpenseModel)
        .filter(
            ExpenseModel.id == expense_id,
            ExpenseModel.user_id == user_id,
        )
        .first()
    )

    if expense_model is None:
        raise ExpenseNotFoundError()

    return expense_model


# Updates an existing expense owned by the authenticated user.
# This function exists to isolate PostgreSQL update logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - expense_data: validated partial expense update data.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - Updated ExpenseModel instance.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def update_expense(
    db_session: Session,
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    user_id: UUID,
) -> ExpenseModel:
    expense_model = get_expense_by_id(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    update_data = expense_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(expense_model, field_name, field_value)

    db_session.commit()
    db_session.refresh(expense_model)

    return expense_model


# Deletes an existing expense owned by the authenticated user.
# This function exists to isolate PostgreSQL delete logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - None.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def delete_expense(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> None:
    expense_model = get_expense_by_id(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    db_session.delete(expense_model)
    db_session.commit()