from sqlalchemy.orm import Session
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Creates a new expense record in PostgreSQL.
# This function exists to isolate database write logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data from the service layer.
# Returns:
# - ExpenseResponse object created from the saved database model.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
) -> ExpenseResponse:
    expense_model = ExpenseModel(
        amount=expense_data.amount,
        category=expense_data.category,
        description=expense_data.description,
        date=expense_data.date,
    )

    db_session.add(expense_model)
    db_session.commit()
    db_session.refresh(expense_model)

    return ExpenseResponse.model_validate(expense_model)


# Returns all expense records from PostgreSQL.
# This function exists to isolate database read logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of ExpenseResponse objects created from database models.
def get_expenses(db_session: Session) -> list[ExpenseResponse]:
    expense_models = db_session.query(ExpenseModel).all()

    return [
        ExpenseResponse.model_validate(expense_model)
        for expense_model in expense_models
    ]