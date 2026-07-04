from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate


# Creates a new expense database record.
# This function exists to isolate PostgreSQL write logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data from the service layer.
# Returns:
# - ExpenseModel instance saved in the database.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
) -> ExpenseModel:
    expense_model = ExpenseModel(
        user_id=expense_data.user_id,
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