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

    request_body = {
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    headers = {"X-User-Id": user_id}

    # Act
    response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers=headers,
    )
    response_data = response.json()

    # Assert
    assert response.status_code == 201
    assert response_data["user_id"] == user_id
    assert response_data["name"] == request_body["name"]
    assert response_data["color"] == request_body["color"]
    assert response_data["icon"] == request_body["icon"]
    assert response_data["is_default"] is False
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the categories list endpoint returns categories for the authenticated user only.
# This test exists to verify that clients can fetch only their own categories stored in PostgreSQL.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the authenticated user's category is returned by the API.
def test_get_categories_endpoint_returns_authenticated_user_categories(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    user_request_body = {
        "name": "Transport",
        "color": "#2563EB",
        "icon": "car",
    }

    other_user_request_body = {
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    user_create_response = client.post(
        "/api/v1/categories",
        json=user_request_body,
        headers={"X-User-Id": user_id},
    )
    other_user_create_response = client.post(
        "/api/v1/categories",
        json=other_user_request_body,
        headers={"X-User-Id": other_user_id},
    )

    assert user_create_response.status_code == 201
    assert other_user_create_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/categories",
        headers={"X-User-Id": user_id},
    )
    response_data = response.json()

    # Assert
    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["name"] == user_request_body["name"]
    assert response_data[0]["color"] == user_request_body["color"]
    assert response_data[0]["icon"] == user_request_body["icon"]


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

    request_body = {
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    first_response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers={"X-User-Id": user_id},
    )

    assert first_response.status_code == 201

    # Act
    response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers={"X-User-Id": user_id},
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Category with this name already exists for this user."


# Tests that the same category name can be used by different users.
# This test exists to verify that the unique category constraint is scoped by user_id.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both users can create a category with the same name.
def test_create_category_endpoint_allows_same_name_for_different_users(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    request_body = {
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    # Act
    first_response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers={"X-User-Id": user_id},
    )
    second_response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers={"X-User-Id": other_user_id},
    )

    # Assert
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["user_id"] == user_id
    assert second_response.json()["user_id"] == other_user_id


# Tests that the API rejects requests without authentication header.
# This test exists to verify that the temporary auth dependency protects the categories endpoint.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_categories_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/categories")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-User-Id header."