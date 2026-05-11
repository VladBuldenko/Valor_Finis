from app.modules.categories import service
from app.modules.categories.schemas import CategoryResponse


# Tests that the service returns available categories.
# This test exists to verify that the service layer correctly provides category data.
# Parameters:
# - None.
# Returns:
# - None. The test passes if categories are returned successfully.
def test_get_categories_returns_categories() -> None:
    # Arrange
    expected_categories_count = 8

    # Act
    categories = service.get_categories()

    # Assert
    assert len(categories) == expected_categories_count
    assert all(isinstance(category, CategoryResponse) for category in categories)


# Tests that the service returns the food category.
# This test exists to verify that core default categories are available through the service layer.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the food category exists.
def test_get_categories_includes_food_category() -> None:
    # Arrange
    expected_category_key = "food"

    # Act
    categories = service.get_categories()
    category_keys = [category.key for category in categories]

    # Assert
    assert expected_category_key in category_keys