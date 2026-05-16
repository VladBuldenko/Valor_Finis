from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Tests that the repository creates a new expense in the database session.
# This test exists to verify that expense data is converted into ExpenseModel and persisted through SQLAlchemy.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the database session receives the expected calls and response data is correct.
def test_create_expense_creates_new_expense() -> None:
    # Arrange
    db_session = MagicMock()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    # Act
    created_expense = expenses_repository.create_expense(db_session, expense_data)

    # Assert
    db_session.add.assert_called_once()
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once()

    saved_model = db_session.add.call_args.args[0]

    assert isinstance(saved_model, ExpenseModel)
    assert saved_model.amount == Decimal("24.99")
    assert saved_model.category == "food"
    assert saved_model.description == "Lidl groceries"
    assert saved_model.date == date(2026, 5, 7)
    assert isinstance(created_expense, ExpenseResponse)


# Tests that the repository returns expense records from the database session.
# This test exists to verify that database models are converted into ExpenseResponse objects.
# Parameters:
# - None.
# Returns:
# - None. The test passes if get_expenses returns expected response objects.
def test_get_expenses_returns_expenses_from_database() -> None:
    # Arrange
    db_session = MagicMock()

    expense_model = ExpenseModel(
        id=1,
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
        created_at=datetime(2026, 5, 7, 12, 0, 0),
    )

    db_session.query.return_value.all.return_value = [expense_model]

    # Act
    expenses = expenses_repository.get_expenses(db_session)

    # Assert
    assert len(expenses) == 1
    assert expenses[0].id == 1
    assert expenses[0].amount == Decimal("24.99")
    assert expenses[0].category == "food"
    assert expenses[0].description == "Lidl groceries"
    assert expenses[0].date == date(2026, 5, 7)

    db_session.query.assert_called_once_with(ExpenseModel)