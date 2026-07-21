from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_budget


# Tests that the API creates a new budget successfully.
# This test exists to verify the full request flow: router -> auth dependency -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_budget_endpoint_creates_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "name": "Food budget",
        "limit_amount": 400,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["user_id"] == user_id
    assert response_data["category_id"] is None
    assert response_data["name"] == payload["name"]
    assert response_data["limit_amount"] == "400.00"
    assert response_data["currency"] == payload["currency"]
    assert response_data["period"] == payload["period"]
    assert response_data["start_date"] == payload["start_date"]
    assert response_data["end_date"] is None
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the API returns budgets for the authenticated user only.
# This test exists to verify that saved budgets are filtered by the user resolved from authentication data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains only the authenticated user's budget.
def test_get_budgets_endpoint_returns_authenticated_user_budgets(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )
    create_budget(
        client=client,
        user_id=other_user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=100,
    )

    # Act
    response = client.get(
        "/api/v1/budgets",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["category_id"] is None
    assert response_data[0]["name"] == "Food budget"
    assert response_data[0]["limit_amount"] == "400.00"
    assert response_data[0]["currency"] == "EUR"
    assert response_data[0]["period"] == "monthly"
    assert response_data[0]["start_date"] == "2026-05-01"
    assert response_data[0]["end_date"] is None


# Tests that the API rejects a budget with zero limit amount.
# This test exists to verify that request validation works before database persistence.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_budget_endpoint_rejects_zero_limit_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "name": "Invalid budget",
        "limit_amount": 0,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that duplicate budget creation returns a conflict error.
# This test exists to verify that the API protects users from duplicate budget definitions.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the second request returns HTTP 409.
def test_create_budget_endpoint_returns_conflict_for_duplicate_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "name": "Food budget",
        "limit_amount": 400,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Budget with this name, period, and start date already exists for this user."
    )


# Tests that the same budget definition can be used by different users.
# This test exists to verify that the unique budget constraint is scoped by user_id.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both users can create the same budget definition.
def test_create_budget_endpoint_allows_same_budget_for_different_users(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    # Act
    first_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )
    second_budget = create_budget(
        client=client,
        user_id=other_user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    # Assert
    assert first_budget["user_id"] == user_id
    assert second_budget["user_id"] == other_user_id
    assert first_budget["name"] == "Food budget"
    assert second_budget["name"] == "Food budget"
    assert first_budget["id"] != second_budget["id"]


# Tests that the API rejects requests without authentication header.
# This test exists to verify that the temporary auth dependency protects the budgets endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_budgets_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/budgets")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-User-Id header."

# Tests that the API updates an authenticated user's budget.
# This test exists to verify the PATCH flow: router -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains updated budget data.
def test_update_budget_endpoint_updates_authenticated_user_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    payload = {
        "limit_amount": 550,
        "end_date": "2026-05-31",
    }

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    response_data = response.json()

    assert response_data["id"] == created_budget["id"]
    assert response_data["user_id"] == user_id
    assert response_data["category_id"] is None
    assert response_data["name"] == "Food budget"
    assert response_data["limit_amount"] == "550.00"
    assert response_data["currency"] == "EUR"
    assert response_data["period"] == "monthly"
    assert response_data["start_date"] == "2026-05-01"
    assert response_data["end_date"] == "2026-05-31"


# Tests that the API rejects updating another user's budget.
# This test exists to verify ownership protection for PATCH requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_update_budget_endpoint_rejects_other_user_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_budget = create_budget(
        client=client,
        user_id=other_user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=100,
    )

    payload = {
        "limit_amount": 150,
    }

    # Act
    response = client.patch(
        f"/api/v1/budgets/{other_user_budget['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Budget not found."


# Tests that the API rejects empty budget update payloads.
# This test exists to verify that PATCH requests must contain at least one editable field.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_budget_endpoint_rejects_empty_payload(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects budget updates with invalid limit amount.
# This test exists to verify that PATCH validation prevents zero or negative budget limits.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_budget_endpoint_rejects_zero_limit_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    payload = {
        "limit_amount": 0,
    }

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects budget update when the new definition already exists for the same user.
# This test exists to verify that duplicate budget definitions are protected during PATCH requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns conflict status code.
def test_update_budget_endpoint_returns_conflict_for_duplicate_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    budget_to_update = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=100,
    )

    payload = {
        "name": "Food budget",
    }

    # Act
    response = client.patch(
        f"/api/v1/budgets/{budget_to_update['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Budget with this name, period, and start date already exists for this user."
    )


# Tests that the API deletes an authenticated user's budget.
# This test exists to verify the DELETE flow and that deleted budgets no longer appear in the list.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns no content and the budget is removed.
def test_delete_budget_endpoint_deletes_authenticated_user_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    # Act
    delete_response = client.delete(
        f"/api/v1/budgets/{created_budget['id']}",
        headers=auth_headers(user_id),
    )

    get_response = client.get(
        "/api/v1/budgets",
        headers=auth_headers(user_id),
    )

    # Assert
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert get_response.status_code == 200
    assert get_response.json() == []


# Tests that the API rejects deleting another user's budget.
# This test exists to verify ownership protection for DELETE requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_delete_budget_endpoint_rejects_other_user_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_budget = create_budget(
        client=client,
        user_id=other_user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=100,
    )

    # Act
    response = client.delete(
        f"/api/v1/budgets/{other_user_budget['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Budget not found."