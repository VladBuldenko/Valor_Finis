from uuid import UUID, uuid4
from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_category
from app.db.database_session import SessionLocal
from app.modules.categories.category_models import CategoryModel


# Marks an existing category as a protected default category.
# This helper exists because the public API intentionally prevents
# clients from controlling the is_default field.
# Parameters:
# - category_id: category identifier returned by the API.
# Returns:
# - None.
def mark_category_as_default(category_id: str) -> None:
    db_session = SessionLocal()

    try:
        category_model = db_session.get(
            CategoryModel,
            UUID(category_id),
        )

        assert category_model is not None

        category_model.is_default = True

        db_session.commit()
    finally:
        db_session.close()

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
    assert response.json()["detail"] == "Missing authentication credentials."

    # Tests that the category creation endpoint rejects requests without authentication header.
# This test exists to verify that users cannot create categories without authentication data.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_create_category_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    request_body = {
        "name": "Food",
        "color": "#FF5733",
        "icon": "utensils",
    }

    # Act
    response = client.post(
        "/api/v1/categories",
        json=request_body,
    )

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."

# Tests that the API updates an authenticated user's category.
# This test exists to verify the PATCH flow: router -> service -> repository -> PostgreSQL.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the response contains updated category data.
def test_update_category_endpoint_updates_authenticated_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    request_body = {
        "name": "Groceries",
        "color": "#22C55E",
        "icon": "shopping-cart",
    }

    # Act
    response = client.patch(
        f"/api/v1/categories/{created_category['id']}",
        json=request_body,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    response_data = response.json()

    assert response_data["id"] == created_category["id"]
    assert response_data["user_id"] == user_id
    assert response_data["name"] == request_body["name"]
    assert response_data["color"] == request_body["color"]
    assert response_data["icon"] == request_body["icon"]
    assert response_data["is_default"] is False
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the API rejects updating another user's category.
# This test exists to verify ownership protection for PATCH requests.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_update_category_endpoint_rejects_other_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    request_body = {
        "name": "Groceries",
    }

    # Act
    response = client.patch(
        f"/api/v1/categories/{other_user_category['id']}",
        json=request_body,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found."


# Tests that the API rejects empty category update payloads.
# This test exists to verify that PATCH requests must contain at least one editable field.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_category_endpoint_rejects_empty_payload(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    # Act
    response = client.patch(
        f"/api/v1/categories/{created_category['id']}",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects category update when the new name already exists for the same user.
# This test exists to verify that duplicate category names are protected during PATCH requests.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns conflict status code.
def test_update_category_endpoint_returns_conflict_for_duplicate_name(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )
    category_to_update = create_category(
        client=client,
        user_id=user_id,
        name="Transport",
    )

    request_body = {
        "name": "Food",
    }

    # Act
    response = client.patch(
        f"/api/v1/categories/{category_to_update['id']}",
        json=request_body,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Category with this name already exists for this user."


# Tests that the API deletes an authenticated user's category.
# This test exists to verify the DELETE flow and that deleted categories no longer appear in the list.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns no content and the category is removed.
def test_delete_category_endpoint_deletes_authenticated_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    # Act
    delete_response = client.delete(
        f"/api/v1/categories/{created_category['id']}",
        headers=auth_headers(user_id),
    )

    get_response = client.get(
        "/api/v1/categories",
        headers=auth_headers(user_id),
    )

    # Assert
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert get_response.status_code == 200
    assert get_response.json() == []


# Tests that the API rejects deleting another user's category.
# This test exists to verify ownership protection for DELETE requests.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_delete_category_endpoint_rejects_other_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    # Act
    response = client.delete(
        f"/api/v1/categories/{other_user_category['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found."

    # Tests that category names and optional UI fields are normalized.
# This test exists to prevent unnecessary whitespace
# from being persisted in category data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_create_category_endpoint_normalizes_category_data(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/categories",
        json={
            "name": "  Weekly   groceries  ",
            "color": "  #22C55E  ",
            "icon": "  shopping-cart  ",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 201, response.text

    response_data = response.json()

    assert response_data["name"] == "Weekly groceries"
    assert response_data["color"] == "#22C55E"
    assert response_data["icon"] == "shopping-cart"

    # Tests that category names are unique regardless of letter case.
# This test exists to prevent visually duplicated categories
# such as Food, food, and FOOD for the same user.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_create_category_endpoint_rejects_case_insensitive_duplicate(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    response = client.post(
        "/api/v1/categories",
        json={
            "name": "  fOoD  ",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Category with this name already exists for this user."
        ),
    }

    # Tests that category rename checks are case-insensitive.
# This test exists to prevent renaming one category
# into another existing category with different letter case.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_update_category_endpoint_rejects_case_insensitive_duplicate(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    category_to_update = create_category(
        client=client,
        user_id=user_id,
        name="Transport",
    )

    response = client.patch(
        f"/api/v1/categories/{category_to_update['id']}",
        json={
            "name": "  FOOD  ",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Category with this name already exists for this user."
        ),
    }

    # Tests that default categories cannot be modified.
# This test exists to protect categories managed by the backend.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_update_category_endpoint_rejects_default_category(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    mark_category_as_default(
        category_id=category["id"],
    )

    response = client.patch(
        f"/api/v1/categories/{category['id']}",
        json={
            "name": "Groceries",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Default category cannot be modified.",
    }

    get_response = client.get(
        f"/api/v1/categories/{category['id']}",
        headers=auth_headers(user_id),
    )

    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Food"
    assert get_response.json()["is_default"] is True

    # Tests that default categories cannot be deleted.
# This test exists to keep protected backend-managed categories available.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_delete_category_endpoint_rejects_default_category(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    mark_category_as_default(
        category_id=category["id"],
    )

    response = client.delete(
        f"/api/v1/categories/{category['id']}",
        headers=auth_headers(user_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Default category cannot be deleted.",
    }

    get_response = client.get(
        f"/api/v1/categories/{category['id']}",
        headers=auth_headers(user_id),
    )

    assert get_response.status_code == 200
    assert get_response.json()["is_default"] is True

    # Tests that deleting a category keeps linked expenses
# and clears their category_id.
# This test exists to verify the database ON DELETE SET NULL rule.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_delete_category_endpoint_clears_expense_category(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    expense_response = client.post(
        "/api/v1/expenses",
        json={
            "category_id": category["id"],
            "title": "Groceries",
            "amount": "24.99",
            "currency": "EUR",
            "expense_date": "2026-08-03",
            "description": "Weekly groceries",
            "source": "manual",
        },
        headers=auth_headers(user_id),
    )

    assert expense_response.status_code == 201, expense_response.text

    created_expense = expense_response.json()

    delete_response = client.delete(
        f"/api/v1/categories/{category['id']}",
        headers=auth_headers(user_id),
    )

    assert delete_response.status_code == 204

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200, expenses_response.text

    stored_expenses = expenses_response.json()

    assert len(stored_expenses) == 1
    assert stored_expenses[0]["id"] == created_expense["id"]
    assert stored_expenses[0]["category_id"] is None
    assert stored_expenses[0]["title"] == "Groceries"
    assert stored_expenses[0]["amount"] == "24.99"