from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_category


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

    # Act
    response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers=auth_headers(user_id),
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

    create_category(
        client=client,
        user_id=user_id,
        name="Transport",
    )
    create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    # Act
    response = client.get(
        "/api/v1/categories",
        headers=auth_headers(user_id),
    )
    response_data = response.json()

    # Assert
    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["name"] == "Transport"


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

    create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    # Act
    response = client.post(
        "/api/v1/categories",
        json=request_body,
        headers=auth_headers(user_id),
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

    # Act
    first_category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )
    second_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    # Assert
    assert first_category["user_id"] == user_id
    assert second_category["user_id"] == other_user_id
    assert first_category["name"] == "Food"
    assert second_category["name"] == "Food"
    assert first_category["id"] != second_category["id"]


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