from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import BudgetCreate
from app.modules.categories import service
from app.modules.categories.default_categories import DEFAULT_CATEGORIES
from app.modules.categories.errors import CategoryInUseByBudgetError
from app.modules.categories.schemas import CategoryCreate, CategoryResponse, CategoryUpdate
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate


# Tests that the service creates a category and returns a response schema.
# This test exists to verify that the service layer maps database models to API responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created category response contains the expected values.
def test_create_category_returns_category_response(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    category_data = CategoryCreate(
        name="Food",
        color="#FF5733",
        icon="utensils",
    )

    try:
        # Act
        category = service.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )

        # Assert
        assert isinstance(category, CategoryResponse)
        assert category.user_id == user_id
        assert category.name == category_data.name
        assert category.color == category_data.color
        assert category.icon == category_data.icon
        assert category.is_default is False
        assert category.id is not None
        assert category.created_at is not None
        assert category.updated_at is not None
    finally:
        db_session.close()


# Tests that the service returns categories for a specific user.
# This test exists to verify that the service layer provides user-scoped category responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the service returns only the requested user's categories.
def test_get_categories_returns_user_category_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_category_data = CategoryCreate(
    name="Vacation",
    color="#2563EB",
    icon="plane",
    )

    other_user_category_data = CategoryCreate(
    name="Pets",
    color="#FF5733",
    icon="paw",
    )

    try:
        service.create_category(
            db_session=db_session,
            category_data=user_category_data,
            user_id=user_id,
        )
        service.create_category(
            db_session=db_session,
            category_data=other_user_category_data,
            user_id=other_user_id,
        )

        # Act
        categories = service.get_categories(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(categories) == len(DEFAULT_CATEGORIES) + 1
        assert all(isinstance(category, CategoryResponse) for category in categories)
        assert all(category.user_id == user_id for category in categories)

        custom_categories = [
            category for category in categories if category.is_default is False
        ]

        assert len(custom_categories) == 1
        assert custom_categories[0].name == user_category_data.name
        assert custom_categories[0].color == user_category_data.color
        assert custom_categories[0].icon == user_category_data.icon
    finally:
        db_session.close()


# Tests that deleting a category still referenced by a budget is rejected.
# This test exists to close the live bug where deleting a category a budget
# scopes to used to silently turn that budget into an all-expenses budget.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryInUseByBudgetError is raised and the
#   category still exists.
def test_delete_category_rejects_category_referenced_by_budget(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        category = service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Hobbies"),
            user_id=user_id,
        )

        budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=category.id,
                name="Entertainment budget",
                limit_amount=Decimal("300"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryInUseByBudgetError):
            service.delete_category(
                db_session=db_session,
                category_id=category.id,
                user_id=user_id,
            )

        categories = service.get_categories(
            db_session=db_session,
            user_id=user_id,
        )
        assert any(c.id == category.id for c in categories)
    finally:
        db_session.close()


# Tests that a category referenced only by an expense (not a budget) can
# still be deleted.
# This test exists to document the deliberate non-change from Part 5: only
# a budget's category_id going null silently inverts its meaning, an
# expense degrading to "Uncategorized" does not, so expense-only references
# stay unaffected by this guard.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if delete_category succeeds.
def test_delete_category_allows_category_referenced_only_by_expense(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        category = service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Snacks"),
            user_id=user_id,
        )

        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                category_id=category.id,
                title="Chips",
                amount=Decimal("5"),
                currency="EUR",
                expense_date=date(2026, 5, 7),
                description="Chips",
                source="manual",
            ),
            user_id=user_id,
        )

        # Act
        service.delete_category(
            db_session=db_session,
            category_id=category.id,
            user_id=user_id,
        )

        # Assert
        categories = service.get_categories(
            db_session=db_session,
            user_id=user_id,
        )
        assert all(c.id != category.id for c in categories)
    finally:
        db_session.close()


# Tests that hiding (is_visible=False) a category still referenced by a
# budget succeeds, since hiding does not break the budget's reference.
# This test exists to verify the is_visible precedent is the intended
# steer away from deletion, per Part 5.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the category is updated to is_visible=False.
def test_update_category_hides_referenced_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        category = service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Hobbies"),
            user_id=user_id,
        )

        budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=category.id,
                name="Entertainment budget",
                limit_amount=Decimal("300"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act
        updated_category = service.update_category(
            db_session=db_session,
            category_id=category.id,
            category_data=CategoryUpdate(is_visible=False),
            user_id=user_id,
        )

        # Assert
        assert updated_category.is_visible is False
    finally:
        db_session.close()