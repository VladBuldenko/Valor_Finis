from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.categories import service
from app.modules.categories.default_categories import DEFAULT_CATEGORIES
from app.modules.categories.schemas import CategoryCreate, CategoryResponse


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