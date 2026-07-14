from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Tests that the service creates an expense response from a repository model.
# This test exists to verify that the service calls the repository with authenticated user id and maps the returned model to ExpenseResponse.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if ExpenseResponse contains expected values.
def test_service_create_expense_returns_expense_response(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expected_db_session = db_session

    expense_id = uuid4()
    user_id = uuid4()
    expected_user_id = user_id

    created_at = datetime(2026, 5, 7, 10, 30, 0)
    updated_at = datetime(2026, 5, 7, 10, 30, 0)

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )
    expected_expense_data = expense_data

    expense_model = SimpleNamespace(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title=expense_data.title,
        amount=expense_data.amount,
        currency=expense_data.currency,
        expense_date=expense_data.expense_date,
        description=expense_data.description,
        source=expense_data.source,
        created_at=created_at,
        updated_at=updated_at,
    )

    def fake_create_expense(
        db_session: Session,
        expense_data: ExpenseCreate,
        user_id: UUID,
    ) -> SimpleNamespace:
        assert db_session is expected_db_session
        assert expense_data == expected_expense_data
        assert user_id == expected_user_id

        return expense_model

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "create_expense",
        fake_create_expense,
    )

    # Act
    created_expense = expenses_service.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
    )

    # Assert
    assert isinstance(created_expense, ExpenseResponse)
    assert created_expense.id == expense_id
    assert created_expense.user_id == user_id
    assert created_expense.category_id is None
    assert created_expense.title == expense_data.title
    assert created_expense.amount == Decimal("24.99")
    assert created_expense.currency == expense_data.currency
    assert created_expense.expense_date == expense_data.expense_date
    assert created_expense.description == expense_data.description
    assert created_expense.source == expense_data.source
    assert created_expense.created_at == created_at
    assert created_expense.updated_at == updated_at


# Tests that the service returns expense response objects for a specific user.
# This test exists to verify that the service passes user_id to the repository and maps returned models to responses.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if a list of ExpenseResponse objects is returned.
def test_service_get_expenses_returns_expense_responses_for_user(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expected_db_session = db_session

    expense_id = uuid4()
    user_id = uuid4()
    expected_user_id = user_id

    created_at = datetime(2026, 5, 7, 10, 30, 0)
    updated_at = datetime(2026, 5, 7, 10, 30, 0)

    expense_model = SimpleNamespace(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
        created_at=created_at,
        updated_at=updated_at,
    )

    def fake_get_expenses(
        db_session: Session,
        user_id: UUID,
    ) -> list[SimpleNamespace]:
        assert db_session is expected_db_session
        assert user_id == expected_user_id

        return [expense_model]

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )

    # Act
    expenses = expenses_service.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    assert len(expenses) == 1
    assert isinstance(expenses[0], ExpenseResponse)
    assert expenses[0].id == expense_id
    assert expenses[0].user_id == user_id
    assert expenses[0].category_id is None
    assert expenses[0].title == "Lidl groceries"
    assert expenses[0].amount == Decimal("24.99")
    assert expenses[0].currency == "EUR"
    assert expenses[0].expense_date == date(2026, 5, 7)
    assert expenses[0].description == "Milk, bread and fruits"
    assert expenses[0].source == "manual"
    assert expenses[0].created_at == created_at
    assert expenses[0].updated_at == updated_at