from uuid import uuid4

from fastapi.testclient import TestClient


# Tests that the API creates a new expense successfully.
# This test exists to verify the full request flow: router -> auth dependency -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_expense_endpoint_creates_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    headers = {"X-User-Id": user_id}

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=headers,
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["user_id"] == user_id
    assert response_data["category_id"] is None
    assert response_data["title"] == payload["title"]
    assert response_data["amount"] == "24.99"
    assert response_data["currency"] == payload["currency"]
    assert response_data["expense_date"] == payload["expense_date"]
    assert response_data["description"] == payload["description"]
    assert response_data["source"] == payload["source"]
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the API returns expenses for the authenticated user only.
# This test exists to verify that saved expenses are filtered by the user resolved from authentication data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains only the authenticated user's expense.
def test_get_expenses_endpoint_returns_authenticated_user_expenses(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    user_payload = {
        "category_id": None,
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    other_user_payload = {
        "category_id": None,
        "title": "Train ticket",
        "amount": 12.50,
        "currency": "EUR",
        "expense_date": "2026-05-08",
        "description": "Munich transport",
        "source": "manual",
    }

    user_create_response = client.post(
        "/api/v1/expenses",
        json=user_payload,
        headers={"X-User-Id": user_id},
    )
    other_user_create_response = client.post(
        "/api/v1/expenses",
        json=other_user_payload,
        headers={"X-User-Id": other_user_id},
    )

    assert user_create_response.status_code == 201
    assert other_user_create_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/expenses",
        headers={"X-User-Id": user_id},
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["category_id"] is None
    assert response_data[0]["title"] == user_payload["title"]
    assert response_data[0]["amount"] == "24.99"
    assert response_data[0]["currency"] == user_payload["currency"]
    assert response_data[0]["expense_date"] == user_payload["expense_date"]
    assert response_data[0]["description"] == user_payload["description"]
    assert response_data[0]["source"] == user_payload["source"]


# Tests that the API rejects an expense with zero amount.
# This test exists to verify that request validation works before database persistence.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_expense_endpoint_rejects_zero_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "title": "Invalid expense",
        "amount": 0,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Invalid expense",
        "source": "manual",
    }

    headers = {"X-User-Id": user_id}

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=headers,
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects requests without authentication header.
# This test exists to verify that the temporary auth dependency protects the expenses endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_expenses_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/expenses")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-User-Id header."