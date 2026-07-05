from uuid import uuid4

from fastapi.testclient import TestClient


# Tests that the category creation endpoint creates a category in the database.
# This test exists to verify that mobile and web clients can create user categories through the API.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_category_endpoint_creates_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    expected_status_code = 201

    request_body = {
        "user_id": user_id,
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    # Act
    response = client.post("/api/v1/categories", json=request_body)
    response_data = response.json()

    # Assert
    assert response.status_code == expected_status_code
    assert response_data["user_id"] == user_id
    assert response_data["name"] == request_body["name"]
    assert response_data["color"] == request_body["color"]
    assert response_data["icon"] == request_body["icon"]
    assert response_data["is_default"] is False
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the categories list endpoint returns categories for a user.
# This test exists to verify that clients can fetch categories stored in PostgreSQL.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created category is returned by the API.
def test_get_categories_endpoint_returns_user_categories(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    expected_status_code = 200

    request_body = {
        "user_id": user_id,
        "name": "Transport",
        "color": "#2563EB",
        "icon": "car",
    }

    client.post("/api/v1/categories", json=request_body)

    # Act
    response = client.get("/api/v1/categories", params={"user_id": user_id})
    response_data = response.json()

    # Assert
    assert response.status_code == expected_status_code
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["name"] == request_body["name"]
    assert response_data[0]["color"] == request_body["color"]
    assert response_data[0]["icon"] == request_body["icon"]


# Tests that duplicate category creation returns a conflict error.
# This test exists to verify that the API protects users from duplicate category names.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the second request returns HTTP 409.
def test_create_category_endpoint_returns_conflict_for_duplicate_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    expected_status_code = 409

    request_body = {
        "user_id": user_id,
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    client.post("/api/v1/categories", json=request_body)

    # Act
    response = client.post("/api/v1/categories", json=request_body)

    # Assert
    assert response.status_code == expected_status_code