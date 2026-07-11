from uuid import uuid4

from fastapi.testclient import TestClient


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

    headers = {"X-User-Id": user_id}

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=headers,
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

    user_payload = {
        "category_id": None,
        "name": "Food budget",
        "limit_amount": 400,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    other_user_payload = {
        "category_id": None,
        "name": "Transport budget",
        "limit_amount": 100,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    user_create_response = client.post(
        "/api/v1/budgets",
        json=user_payload,
        headers={"X-User-Id": user_id},
    )
    other_user_create_response = client.post(
        "/api/v1/budgets",
        json=other_user_payload,
        headers={"X-User-Id": other_user_id},
    )

    assert user_create_response.status_code == 201
    assert other_user_create_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/budgets",
        headers={"X-User-Id": user_id},
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["category_id"] is None
    assert response_data[0]["name"] == user_payload["name"]
    assert response_data[0]["limit_amount"] == "400.00"
    assert response_data[0]["currency"] == user_payload["currency"]
    assert response_data[0]["period"] == user_payload["period"]
    assert response_data[0]["start_date"] == user_payload["start_date"]
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

    headers = {"X-User-Id": user_id}

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=headers,
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

    headers = {"X-User-Id": user_id}

    first_response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=headers,
    )

    assert first_response.status_code == 201

    # Act
    response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers=headers,
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
    first_response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers={"X-User-Id": user_id},
    )
    second_response = client.post(
        "/api/v1/budgets",
        json=payload,
        headers={"X-User-Id": other_user_id},
    )

    # Assert
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["user_id"] == user_id
    assert second_response.json()["user_id"] == other_user_id


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