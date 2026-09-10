from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
)
from app.modules.categories import service as categories_service
from app.modules.categories.errors import CategoryNotFoundError
from app.modules.categories.schemas import CategoryCreate


# Tests that the service creates a budget and returns a response schema.
# This test exists to verify that the service layer maps database models to API responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created budget response contains the expected values.
def test_create_budget_returns_budget_response(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
        )

        # Assert
        assert isinstance(budget, BudgetResponse)
        assert budget.user_id == user_id
        assert budget.category_id is None
        assert budget.name == budget_data.name
        assert budget.limit_amount == Decimal("400")
        assert budget.currency == budget_data.currency
        assert budget.period == budget_data.period
        assert budget.start_date == budget_data.start_date
        assert budget.end_date is None
        assert budget.id is not None
        assert budget.created_at is not None
        assert budget.updated_at is not None
    finally:
        db_session.close()


# Tests that the service returns budgets for a specific user.
# This test exists to verify that the service layer provides user-scoped budget responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the service returns only the requested user's budgets.
def test_get_budgets_returns_user_budget_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    other_user_budget_data = BudgetCreate(
        category_id=None,
        name="Transport budget",
        limit_amount=Decimal("150"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        budget_service.create_budget(
            db_session=db_session,
            budget_data=user_budget_data,
            user_id=user_id,
        )
        budget_service.create_budget(
            db_session=db_session,
            budget_data=other_user_budget_data,
            user_id=other_user_id,
        )

        # Act
        budgets = budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(budgets) == 1
        assert isinstance(budgets[0], BudgetResponse)
        assert budgets[0].user_id == user_id
        assert budgets[0].category_id is None
        assert budgets[0].name == user_budget_data.name
        assert budgets[0].limit_amount == Decimal("400")
        assert budgets[0].currency == user_budget_data.currency
        assert budgets[0].period == user_budget_data.period
        assert budgets[0].start_date == user_budget_data.start_date
        assert budgets[0].end_date is None
    finally:
        db_session.close()


# Tests that a budget can be created with a category owned by the same user.
# This test exists to verify the happy path of category ownership validation
# during budget creation.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created budget references the owned category.
def test_create_budget_allows_authenticated_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=user_id,
        )

        budget_data = BudgetCreate(
            category_id=category.id,
            name="Food budget",
            limit_amount=Decimal("400"),
            currency="EUR",
            period="monthly",
            start_date=date(2026, 5, 1),
            end_date=None,
        )

        # Act
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
        )

        # Assert
        assert budget.category_id == category.id
    finally:
        db_session.close()


# Tests that a budget cannot be created with another user's category.
# This test exists to prevent cross-user category assignment during creation.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_create_budget_rejects_other_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_user_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=other_user_id,
        )

        budget_data = BudgetCreate(
            category_id=other_user_category.id,
            name="Food budget",
            limit_amount=Decimal("400"),
            currency="EUR",
            period="monthly",
            start_date=date(2026, 5, 1),
            end_date=None,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.create_budget(
                db_session=db_session,
                budget_data=budget_data,
                user_id=user_id,
            )

        assert budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        ) == []
    finally:
        db_session.close()


# Tests that a budget cannot be created with a category id that does not exist.
# This test exists to return a controlled domain error instead of relying
# only on a database foreign key failure.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_create_budget_rejects_nonexistent_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
        category_id=uuid4(),
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.create_budget(
                db_session=db_session,
                budget_data=budget_data,
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a budget can be updated to reference a category owned by the same user.
# This test exists to verify the happy path of category ownership validation
# during budget updates.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the updated budget references the owned category.
def test_update_budget_allows_authenticated_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=user_id,
        )

        # Act
        updated_budget = budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(category_id=category.id),
            user_id=user_id,
        )

        # Assert
        assert updated_budget.category_id == category.id
    finally:
        db_session.close()


# Tests that a budget cannot be updated to reference another user's category.
# This test exists to prevent cross-user category assignment during updates.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised and the budget's
#   category is left unchanged.
def test_update_budget_rejects_other_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        other_user_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=other_user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(category_id=other_user_category.id),
                user_id=user_id,
            )

        budgets = budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )
        assert budgets[0].category_id is None
    finally:
        db_session.close()


# Tests that a budget cannot be updated to reference a category id that does
# not exist.
# This test exists to return a controlled domain error instead of relying
# only on a database foreign key failure.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_update_budget_rejects_nonexistent_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(category_id=uuid4()),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that updating a budget without setting category_id does not trigger
# a category ownership lookup.
# This test exists to verify that omitted fields are left untouched and do
# not cause unnecessary category service calls.
# Parameters:
# - monkeypatch: pytest fixture used to observe categories_service calls.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if categories_service.get_category_by_id is never called.
def test_update_budget_skips_category_lookup_when_category_id_omitted(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    category_lookup_calls: list[UUID] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> None:
        category_lookup_calls.append(category_id)

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        monkeypatch.setattr(
            budget_service.categories_service,
            "get_category_by_id",
            fake_get_category_by_id,
        )

        # Act
        updated_budget = budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("500")),
            user_id=user_id,
        )

        # Assert
        assert updated_budget.limit_amount == Decimal("500")
        assert category_lookup_calls == []
    finally:
        db_session.close()