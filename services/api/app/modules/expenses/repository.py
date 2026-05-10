from datetime import datetime
from decimal import Decimal

from app.modules.expenses.schemas import ExpenseCreate, ExpenseResponse


expenses_storage: list[ExpenseResponse] = []
next_expense_id = 1


# Creates a new expense record in temporary in-memory storage.
# This function exists to isolate data storage logic from business logic.
# Parameters:
# - expense_data: validated expense data received from the service layer.
# Returns:
# - ExpenseResponse object with generated id and created_at timestamp.
def create_expense(expense_data: ExpenseCreate) -> ExpenseResponse:
    global next_expense_id

    expense = ExpenseResponse(
        id=next_expense_id,
        amount=expense_data.amount,
        category=expense_data.category,
        description=expense_data.description,
        date=expense_data.date,
        created_at=datetime.utcnow(),
    )

    expenses_storage.append(expense)
    next_expense_id += 1

    return expense


# Returns all expense records from temporary in-memory storage.
# This function exists to keep data retrieval logic inside the repository layer.
# Parameters:
# - None.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses() -> list[ExpenseResponse]:
    return expenses_storage