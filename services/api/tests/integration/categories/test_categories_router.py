from uuid import UUID, uuid4
from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_category
from app.db.database_session import SessionLocal
from app.modules.categories.category_models import CategoryModel
from app.modules.categories.default_categories import DEFAULT_CATEGORIES


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
        name="Pets",
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
    assert len(response_data) == len(DEFAULT_CATEGORIES) + 1
    assert all(category["user_id"] == user_id for category in response_data)

    custom_categories = [
        category for category in response_data if category["is_default"] is False
    ]

    assert len(custom_categories) == 1
    assert custom_categories[0]["name"] == "Pets"


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
        "name": "Hobbies",
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
        name="Pets",
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

    remaining_categories = get_response.json()

    assert len(remaining_categories) == len(DEFAULT_CATEGORIES)
    assert all(category["is_default"] for category in remaining_categories)
    assert not any(
        category["name"] == "Food" for category in remaining_categories
    )


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
        name="Pets",
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


# Finds a bootstrapped default category by its configured name.
# This helper exists so tests can locate a specific predefined category from
# a /categories response without depending on list position.
# Parameters:
# - categories: category list returned by the API.
# - name: configured default category name to find.
# Returns:
# - The matching category dict.
def find_category_by_name(categories: list, name: str) -> dict:
    matches = [category for category in categories if category["name"] == name]

    assert len(matches) == 1

    return matches[0]


# Tests that a brand-new user's first request bootstraps the full predefined
# category set.
# This test exists to verify lazy first-use bootstrap end-to-end through the API.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every configured default category is present.
def test_get_categories_endpoint_bootstraps_default_categories_for_new_user(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.get(
        "/api/v1/categories",
        headers=auth_headers(user_id),
    )
    response_data = response.json()

    # Assert
    assert response.status_code == 200
    assert len(response_data) == len(DEFAULT_CATEGORIES)
    assert all(category["is_default"] is True for category in response_data)
    assert all(category["is_visible"] is True for category in response_data)
    assert {category["system_key"] for category in response_data} == {
        default_category["system_key"] for default_category in DEFAULT_CATEGORIES
    }


# Tests that two different users each get their own independent set of
# predefined categories.
# This test exists to verify that bootstrapped defaults are per-user rows,
# not shared or cached across users.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each user gets a full, disjoint default set.
def test_get_categories_endpoint_bootstraps_independent_defaults_per_user(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    # Act
    response = client.get("/api/v1/categories", headers=auth_headers(user_id))
    other_response = client.get(
        "/api/v1/categories", headers=auth_headers(other_user_id)
    )

    # Assert
    response_data = response.json()
    other_response_data = other_response.json()

    assert len(response_data) == len(DEFAULT_CATEGORIES)
    assert len(other_response_data) == len(DEFAULT_CATEGORIES)
    assert all(category["user_id"] == user_id for category in response_data)
    assert all(
        category["user_id"] == other_user_id for category in other_response_data
    )

    category_ids = {category["id"] for category in response_data}
    other_category_ids = {category["id"] for category in other_response_data}

    assert category_ids.isdisjoint(other_category_ids)


# Tests that a predefined category name is reserved and cannot be reused for
# a custom category.
# This test exists to verify reserved-name protection at the API layer for a
# brand-new user (bootstrap always runs before create, so this is the only
# way to observe the reservation through the public API).
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if creating a category with a reserved name returns a conflict.
def test_create_category_endpoint_rejects_reserved_default_name(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    reserved_name = DEFAULT_CATEGORIES[0]["name"]

    # Act
    response = client.post(
        "/api/v1/categories",
        json={"name": reserved_name},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Category with this name already exists for this user."


# Tests that renaming a custom category onto a reserved predefined name is rejected.
# This test exists to verify reserved-name protection also applies to PATCH renames.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the rename returns a conflict.
def test_update_category_endpoint_rejects_rename_onto_reserved_default_name(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    reserved_name = DEFAULT_CATEGORIES[0]["name"]

    custom_category = create_category(
        client=client,
        user_id=user_id,
        name="Pets",
    )

    # Act
    response = client.patch(
        f"/api/v1/categories/{custom_category['id']}",
        json={"name": reserved_name},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Category with this name already exists for this user."


# Tests that hiding a predefined category does not release its reserved name.
# This test exists to verify the specific product rule that hidden defaults
# still block a custom category from reusing that name.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if creating a category with the hidden default's name still conflicts.
def test_create_category_endpoint_rejects_reserved_name_while_default_is_hidden(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    reserved_name = DEFAULT_CATEGORIES[0]["name"]

    bootstrap_response = client.get(
        "/api/v1/categories", headers=auth_headers(user_id)
    )
    default_category = find_category_by_name(
        bootstrap_response.json(), reserved_name
    )

    hide_response = client.patch(
        f"/api/v1/categories/{default_category['id']}",
        json={"is_visible": False},
        headers=auth_headers(user_id),
    )

    assert hide_response.status_code == 200
    assert hide_response.json()["is_visible"] is False

    # Act
    response = client.post(
        "/api/v1/categories",
        json={"name": reserved_name},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Category with this name already exists for this user."


# Tests that a predefined category can be hidden and then unhidden.
# This test exists to verify the hide/unhide flow keeps the category's
# identity and default protection intact and is not a deletion.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if is_visible flips both ways while everything else stays the same.
def test_update_category_endpoint_hides_and_unhides_default_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    default_name = DEFAULT_CATEGORIES[0]["name"]
    default_system_key = DEFAULT_CATEGORIES[0]["system_key"]

    bootstrap_response = client.get(
        "/api/v1/categories", headers=auth_headers(user_id)
    )
    default_category = find_category_by_name(bootstrap_response.json(), default_name)

    # Act
    hide_response = client.patch(
        f"/api/v1/categories/{default_category['id']}",
        json={"is_visible": False},
        headers=auth_headers(user_id),
    )
    unhide_response = client.patch(
        f"/api/v1/categories/{default_category['id']}",
        json={"is_visible": True},
        headers=auth_headers(user_id),
    )

    # Assert
    assert hide_response.status_code == 200
    hide_data = hide_response.json()
    assert hide_data["is_visible"] is False
    assert hide_data["is_default"] is True
    assert hide_data["system_key"] == default_system_key
    assert hide_data["name"] == default_name

    assert unhide_response.status_code == 200
    unhide_data = unhide_response.json()
    assert unhide_data["is_visible"] is True
    assert unhide_data["is_default"] is True
    assert unhide_data["system_key"] == default_system_key
    assert unhide_data["name"] == default_name


# Tests that hidden categories are excluded from the default category list.
# This test exists to verify the include_hidden=false (default) behavior.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the hidden category is absent from the default response.
def test_get_categories_endpoint_excludes_hidden_categories_by_default(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    default_name = DEFAULT_CATEGORIES[0]["name"]

    bootstrap_response = client.get(
        "/api/v1/categories", headers=auth_headers(user_id)
    )
    default_category = find_category_by_name(bootstrap_response.json(), default_name)

    hide_response = client.patch(
        f"/api/v1/categories/{default_category['id']}",
        json={"is_visible": False},
        headers=auth_headers(user_id),
    )

    assert hide_response.status_code == 200

    # Act
    response = client.get("/api/v1/categories", headers=auth_headers(user_id))
    response_data = response.json()

    # Assert
    assert response.status_code == 200
    assert len(response_data) == len(DEFAULT_CATEGORIES) - 1
    assert not any(category["name"] == default_name for category in response_data)


# Tests that hidden categories are included when include_hidden=true is requested.
# This test exists to verify the include_hidden=true opt-in behavior.
# Parameters:
# - client: TestClient instance connected to the FastAPI app.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the hidden category is present when explicitly requested.
def test_get_categories_endpoint_includes_hidden_categories_when_requested(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    default_name = DEFAULT_CATEGORIES[0]["name"]

    bootstrap_response = client.get(
        "/api/v1/categories", headers=auth_headers(user_id)
    )
    default_category = find_category_by_name(bootstrap_response.json(), default_name)

    hide_response = client.patch(
        f"/api/v1/categories/{default_category['id']}",
        json={"is_visible": False},
        headers=auth_headers(user_id),
    )

    assert hide_response.status_code == 200

    # Act
    response = client.get(
        "/api/v1/categories?include_hidden=true",
        headers=auth_headers(user_id),
    )
    response_data = response.json()

    # Assert
    assert response.status_code == 200
    assert len(response_data) == len(DEFAULT_CATEGORIES)
    hidden_category = find_category_by_name(response_data, default_name)
    assert hidden_category["is_visible"] is False