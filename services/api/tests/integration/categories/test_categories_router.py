from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


# Tests that the categories endpoint returns default categories.
# This test exists to verify that mobile and web clients can fetch available categories through the API.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_get_categories_endpoint_returns_categories() -> None:
    # Arrange
    expected_status_code = 200
    expected_categories_count = 8

    # Act
    response = client.get("/api/v1/categories")
    response_data = response.json()

    # Assert
    assert response.status_code == expected_status_code
    assert len(response_data) == expected_categories_count


# Tests that the categories endpoint includes the food category.
# This test exists to verify that core default categories are exposed through the API.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the food category exists in the API response.
def test_get_categories_endpoint_includes_food_category() -> None:
    # Arrange
    expected_status_code = 200
    expected_category_key = "food"

    # Act
    response = client.get("/api/v1/categories")
    response_data = response.json()
    category_keys = [category["key"] for category in response_data]

    # Assert
    assert response.status_code == expected_status_code
    assert expected_category_key in category_keys