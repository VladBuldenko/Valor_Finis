import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories import repository
from app.modules.categories.default_categories import DEFAULT_CATEGORIES
from app.modules.categories.errors import CategoryAlreadyExistsError
from app.modules.categories.schemas import CategoryCreate
from app.modules.expenses.expenses_models import ExpenseModel


# Tests that the repository creates a category in the database.
# This test exists to verify that category data and authenticated user id are persisted at the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created category has the expected values.
def test_create_category_creates_category(clean_database: None) -> None:
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
        category = repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )

        # Assert
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


# Tests that the repository returns categories for a specific user.
# This test exists to verify that users only receive their own categories.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's category is returned.
def test_get_categories_returns_categories_for_user(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_category_data = CategoryCreate(
        name="Transport",
        color="#2563EB",
        icon="car",
    )

    other_user_category_data = CategoryCreate(
        name="Food",
        color="#FF5733",
        icon="utensils",
    )

    try:
        repository.create_category(
            db_session=db_session,
            category_data=user_category_data,
            user_id=user_id,
        )
        repository.create_category(
            db_session=db_session,
            category_data=other_user_category_data,
            user_id=other_user_id,
        )

        # Act
        categories = repository.get_categories(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(categories) == 1
        assert categories[0].user_id == user_id
        assert categories[0].name == user_category_data.name
        assert categories[0].color == user_category_data.color
        assert categories[0].icon == user_category_data.icon
    finally:
        db_session.close()


# Tests that the repository raises an error for duplicate category names for the same user.
# This test exists to verify that duplicate category conflicts are handled at the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the repository raises CategoryAlreadyExistsError.
def test_create_category_raises_error_for_duplicate_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    category_data = CategoryCreate(
        name="Food",
        color="#FF5733",
        icon="utensils",
    )

    try:
        repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryAlreadyExistsError):
            repository.create_category(
                db_session=db_session,
                category_data=category_data,
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that different users can create categories with the same name.
# This test exists to verify that the unique category constraint is scoped by user_id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both categories are created successfully.
def test_create_category_allows_same_name_for_different_users(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    category_data = CategoryCreate(
        name="Food",
        color="#FF5733",
        icon="utensils",
    )

    try:
        # Act
        first_category = repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )
        second_category = repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=other_user_id,
        )

        # Assert
        assert first_category.user_id == user_id
        assert second_category.user_id == other_user_id
        assert first_category.name == category_data.name
        assert second_category.name == category_data.name
        assert first_category.id != second_category.id
    finally:
        db_session.close()


# Tests that the configured predefined-category catalog itself is well-formed.
# This test exists so bootstrap tests fail loudly on a malformed catalog
# instead of silently passing against duplicate or missing system keys.
# Parameters:
# - None.
# Returns:
# - None. The test passes if every default category has a unique, non-null system_key.
def test_default_categories_have_unique_non_null_system_keys() -> None:
    # Act
    system_keys = [category["system_key"] for category in DEFAULT_CATEGORIES]

    # Assert
    assert len(DEFAULT_CATEGORIES) > 0
    assert all(system_key for system_key in system_keys)
    assert len(system_keys) == len(set(system_keys))


# Tests that bootstrap creates every configured predefined category for a new user.
# This test exists to verify that ensure_default_categories establishes the
# complete predefined category set from a clean state.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the user ends up with exactly the configured defaults.
def test_ensure_default_categories_creates_all_default_categories(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        repository.ensure_default_categories(
            db_session=db_session,
            user_id=user_id,
        )

        categories = repository.get_categories(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(categories) == len(DEFAULT_CATEGORIES)
        assert all(category.is_default is True for category in categories)
        assert all(category.is_visible is True for category in categories)
        assert {category.system_key for category in categories} == {
            default_category["system_key"] for default_category in DEFAULT_CATEGORIES
        }
    finally:
        db_session.close()


# Tests that repeated bootstrap calls do not create duplicate predefined categories.
# This test exists to verify that ensure_default_categories is safe to call on
# every request without accumulating duplicate rows.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the configured default count stays the same after repeated calls.
def test_ensure_default_categories_is_idempotent_on_repeated_calls(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        repository.ensure_default_categories(db_session=db_session, user_id=user_id)
        repository.ensure_default_categories(db_session=db_session, user_id=user_id)
        repository.ensure_default_categories(db_session=db_session, user_id=user_id)

        categories = repository.get_categories(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(categories) == len(DEFAULT_CATEGORIES)
    finally:
        db_session.close()


# Tests that bootstrap promotes an existing matching category in place.
# This test exists to verify that a pre-existing user category with a name
# matching a predefined category keeps its identity and metadata instead of
# being replaced by a newly-created row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the existing category's id, color, and icon are unchanged.
def test_ensure_default_categories_promotes_existing_matching_category_preserving_id(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    default_category = DEFAULT_CATEGORIES[0]

    category_data = CategoryCreate(
        name=default_category["name"].lower(),
        color="#22C55E",
        icon="shopping-cart",
    )

    try:
        existing_category = repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )
        existing_category_id = existing_category.id

        # Act
        repository.ensure_default_categories(
            db_session=db_session,
            user_id=user_id,
        )

        categories = repository.get_categories(
            db_session=db_session,
            user_id=user_id,
        )

        promoted_category = next(
            category for category in categories if category.id == existing_category_id
        )

        # Assert
        assert len(categories) == len(DEFAULT_CATEGORIES)
        assert promoted_category.id == existing_category_id
        assert promoted_category.is_default is True
        assert promoted_category.system_key == default_category["system_key"]
        assert promoted_category.color == category_data.color
        assert promoted_category.icon == category_data.icon
    finally:
        db_session.close()


# Tests that promoting an existing category preserves Expense and Budget
# foreign key relationships pointing at it.
# This test exists to verify that promotion never replaces the category row
# (which would orphan or silently move historical financial data), since
# both Expense.category_id and Budget.category_id reference categories.id
# directly and rely on that id staying stable across promotion.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both relationships still resolve to the promoted category after bootstrap.
def test_ensure_default_categories_promotion_preserves_expense_and_budget_foreign_keys(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    default_category = DEFAULT_CATEGORIES[0]

    category_data = CategoryCreate(name=default_category["name"])

    try:
        existing_category = repository.create_category(
            db_session=db_session,
            category_data=category_data,
            user_id=user_id,
        )
        existing_category_id = existing_category.id

        expense = ExpenseModel(
            user_id=user_id,
            category_id=existing_category_id,
            title="Weekly shop",
            amount=Decimal("42.50"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            source="manual",
        )
        budget = BudgetModel(
            user_id=user_id,
            category_id=existing_category_id,
            name="Monthly limit",
            limit_amount=Decimal("300.00"),
            start_date=date(2026, 5, 1),
        )

        db_session.add(expense)
        db_session.add(budget)
        db_session.commit()

        # Act
        repository.ensure_default_categories(
            db_session=db_session,
            user_id=user_id,
        )

        db_session.expire_all()

        refreshed_expense = db_session.get(ExpenseModel, expense.id)
        refreshed_budget = db_session.get(BudgetModel, budget.id)
        promoted_category = db_session.get(
            repository.CategoryModel,
            existing_category_id,
        )

        # Assert
        assert refreshed_expense is not None
        assert refreshed_budget is not None
        assert refreshed_expense.category_id == existing_category_id
        assert refreshed_budget.category_id == existing_category_id
        assert promoted_category is not None
        assert promoted_category.is_default is True
        assert promoted_category.system_key == default_category["system_key"]
    finally:
        db_session.close()


# Tests that two concurrent first-use bootstrap calls for the same new user
# do not raise an unhandled exception and do not create duplicate categories.
# This test exists to verify the race that occurs when two requests trigger
# bootstrap for the same brand-new user at nearly the same time (e.g. two
# parallel screens fetching categories on app start), reproduced here with
# two genuinely independent PostgreSQL sessions racing against each other
# rather than a sequential simulation.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both calls succeed and exactly one category per
#   configured system_key exists afterward.
def test_ensure_default_categories_concurrent_bootstrap_is_safe(
    clean_database: None,
) -> None:
    # Arrange
    user_id = uuid4()

    # A plain start barrier is not enough: both sessions' SELECT/INSERT round
    # trips against local Postgres are fast enough that one thread can
    # finish entirely before the other is scheduled, so the race never
    # actually happens in practice. Gating commit() instead would deadlock:
    # Postgres's own ON CONFLICT handling makes the second INSERT block
    # (waiting to see whether the first transaction commits or rolls back)
    # before either thread reaches a commit-time barrier. So the barrier
    # goes right after each session's one SELECT (identified via
    # `is_select`, test-only, not a change to repository.py) — this
    # guarantees both sessions read zero existing categories, which is the
    # actual precondition the bootstrap race requires, then lets Postgres's
    # normal row-locking serialize the two INSERTs without any further
    # Python-level gating.
    select_barrier = threading.Barrier(2)

    def bootstrap_in_new_session() -> Optional[str]:
        session = SessionLocal()
        original_execute = session.execute

        def synchronized_execute(statement: object, *args: object, **kwargs: object) -> object:
            result = original_execute(statement, *args, **kwargs)
            if getattr(statement, "is_select", False):
                select_barrier.wait(timeout=5)
            return result

        session.execute = synchronized_execute

        try:
            repository.ensure_default_categories(
                db_session=session,
                user_id=user_id,
            )

            return None
        except Exception as error:  # noqa: BLE001 - captured to assert on, not swallowed
            return f"{type(error).__name__}: {error}"
        finally:
            session.close()

    # Act
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(bootstrap_in_new_session)
        future_b = executor.submit(bootstrap_in_new_session)

        error_a = future_a.result(timeout=10)
        error_b = future_b.result(timeout=10)

    # Assert
    assert error_a is None, error_a
    assert error_b is None, error_b

    verification_session = SessionLocal()

    try:
        categories = repository.get_categories(
            db_session=verification_session,
            user_id=user_id,
        )

        assert len(categories) == len(DEFAULT_CATEGORIES)
        assert {category.system_key for category in categories} == {
            default_category["system_key"] for default_category in DEFAULT_CATEGORIES
        }
    finally:
        verification_session.close()