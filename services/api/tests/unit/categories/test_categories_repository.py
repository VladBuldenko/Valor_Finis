from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.categories import repository
from app.modules.categories.errors import CategoryAlreadyExistsError
from app.modules.categories.schemas import CategoryCreate


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