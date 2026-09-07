from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
)


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
        commit: bool = True,
    ) -> SimpleNamespace:
        assert db_session is expected_db_session
        assert expense_data == expected_expense_data
        assert user_id == expected_user_id
        assert commit is True

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


# Tests that the service updates an expense and returns an expense response.
# This test exists to verify that the service delegates to the repository with
# the correct arguments and maps the returned model to ExpenseResponse.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if ExpenseResponse reflects the updated values.
def test_service_update_expense_returns_expense_response(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expected_db_session = db_session

    expense_id = uuid4()
    expected_expense_id = expense_id
    user_id = uuid4()
    expected_user_id = user_id

    created_at = datetime(2026, 5, 7, 10, 30, 0)
    updated_at = datetime(2026, 5, 7, 11, 0, 0)

    expense_data = ExpenseUpdate(title="Rewe groceries", amount=Decimal("31.20"))
    expected_expense_data = expense_data

    updated_expense_model = SimpleNamespace(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="Rewe groceries",
        amount=Decimal("31.20"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
        created_at=created_at,
        updated_at=updated_at,
    )

    def fake_update_expense(
        db_session: Session,
        expense_id: UUID,
        expense_data: ExpenseUpdate,
        user_id: UUID,
    ) -> SimpleNamespace:
        assert db_session is expected_db_session
        assert expense_id == expected_expense_id
        assert expense_data == expected_expense_data
        assert user_id == expected_user_id

        return updated_expense_model

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "update_expense",
        fake_update_expense,
    )

    # Act
    updated_expense = expenses_service.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=user_id,
    )

    # Assert
    assert isinstance(updated_expense, ExpenseResponse)
    assert updated_expense.id == expense_id
    assert updated_expense.title == "Rewe groceries"
    assert updated_expense.amount == Decimal("31.20")
    assert updated_expense.updated_at == updated_at


# Tests that updating an expense with an explicit category_id validates
# ownership of that category before delegating to the repository.
# This test exists to verify that a user cannot silently attach another
# user's category to their own expense during an update.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/service behavior.
# Returns:
# - None. The test passes if get_category_by_id is called with the update's category_id and user_id.
def test_service_update_expense_validates_category_when_category_id_is_set(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expense_id = uuid4()
    user_id = uuid4()
    category_id = uuid4()

    expense_data = ExpenseUpdate(category_id=category_id)

    validated_category_calls: list[tuple[UUID, UUID]] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> SimpleNamespace:
        validated_category_calls.append((category_id, user_id))
        return SimpleNamespace(id=category_id, user_id=user_id)

    def fake_update_expense(
        db_session: Session,
        expense_id: UUID,
        expense_data: ExpenseUpdate,
        user_id: UUID,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=expense_id,
            user_id=user_id,
            category_id=category_id,
            title="Lidl groceries",
            amount=Decimal("24.99"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            description=None,
            source="manual",
            created_at=datetime(2026, 5, 7, 10, 30, 0),
            updated_at=datetime(2026, 5, 7, 10, 30, 0),
        )

    monkeypatch.setattr(
        expenses_service.categories_service,
        "get_category_by_id",
        fake_get_category_by_id,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "update_expense",
        fake_update_expense,
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=user_id,
    )

    # Assert
    assert validated_category_calls == [(category_id, user_id)]


# Tests that updating an expense without setting category_id does not
# trigger a category ownership check.
# This test exists to verify that omitted fields are left untouched and do
# not cause unnecessary repository/service calls.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/service behavior.
# Returns:
# - None. The test passes if get_category_by_id is never called.
def test_service_update_expense_skips_category_validation_when_category_id_omitted(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expense_id = uuid4()
    user_id = uuid4()

    expense_data = ExpenseUpdate(title="Rewe groceries")

    validated_category_calls: list[UUID] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> SimpleNamespace:
        validated_category_calls.append(category_id)
        return SimpleNamespace(id=category_id, user_id=user_id)

    def fake_update_expense(
        db_session: Session,
        expense_id: UUID,
        expense_data: ExpenseUpdate,
        user_id: UUID,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=expense_id,
            user_id=user_id,
            category_id=None,
            title="Rewe groceries",
            amount=Decimal("24.99"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            description=None,
            source="manual",
            created_at=datetime(2026, 5, 7, 10, 30, 0),
            updated_at=datetime(2026, 5, 7, 10, 30, 0),
        )

    monkeypatch.setattr(
        expenses_service.categories_service,
        "get_category_by_id",
        fake_get_category_by_id,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "update_expense",
        fake_update_expense,
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=user_id,
    )

    # Assert
    assert validated_category_calls == []


# Tests that the service deletes an expense by delegating to the repository.
# This test exists to verify that the service passes db_session, expense_id,
# and user_id through to the repository without additional logic.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if the repository's delete_expense is called with the expected arguments.
def test_service_delete_expense_calls_repository_delete(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    expected_db_session = db_session
    expense_id = uuid4()
    expected_expense_id = expense_id
    user_id = uuid4()
    expected_user_id = user_id

    delete_calls: list[tuple[Session, UUID, UUID]] = []

    def fake_delete_expense(
        db_session: Session,
        expense_id: UUID,
        user_id: UUID,
    ) -> None:
        delete_calls.append((db_session, expense_id, user_id))

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "delete_expense",
        fake_delete_expense,
    )

    # Act
    result = expenses_service.delete_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    # Assert
    assert result is None
    assert delete_calls == [
        (expected_db_session, expected_expense_id, expected_user_id)
    ]