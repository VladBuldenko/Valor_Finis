from app.modules.categories import repository
from app.modules.categories.schemas import CategoryResponse


# Tests that the repository returns the default list of categories.
# This test exists to verify that default expense categories are available.
# Parameters:
# - None.
# Returns:
# - None. The test passes if categories are returned correctly.
def test_get_categories_returns_default_categories() -> None:
    # Act
    categories = repository.get_categories()

    # Assert
    assert len(categories) == 8
    assert all(isinstance(category, CategoryResponse) for category in categories)


# Tests that the default categories include food.
# This test exists to verify that the main expense category "food" is available.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the food category exists.
def test_get_categories_includes_food_category() -> None:
    # Act
    categories = repository.get_categories()
    category_keys = [category.key for category in categories]

    # Assert
    assert "food" in category_keys


# Tests that every category has a key and a name.
# This test exists to verify that category data is complete for API usage.
# Parameters:
# - None.
# Returns:
# - None. The test passes if all categories contain key and name values.
def test_get_categories_returns_categories_with_key_and_name() -> None:
    # Act
    categories = repository.get_categories()

    # Assert
    for category in categories:
        assert category.key
        assert category.name