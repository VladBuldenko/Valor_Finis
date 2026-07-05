from uuid import uuid4

from fastapi.testclient import TestClient


# Tests that the API creates a new budget successfully.
# This test exists to verify the full request flow: router -> service -> repository -> PostgreSQL.
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
        "user_id": user_id,
        "category_id": None,
        "name": "Food budget",
        "limit_amount": 400,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    # Act
    response = client.post("/api/v1/budgets", json=payload)

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


# Tests that the API returns created budgets from PostgreSQL.
# This test exists to verify that saved budgets can be retrieved through the endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains the created budget.
def test_get_budgets_endpoint_returns_user_budgets(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "user_id": user_id,
        "category_id": None,
        "name": "Food budget",
        "limit_amount": 400,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    client.post("/api/v1/budgets", json=payload)

    # Act
    response = client.get("/api/v1/budgets", params={"user_id": user_id})

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["category_id"] is None
    assert response_data[0]["name"] == payload["name"]
    assert response_data[0]["limit_amount"] == "400.00"
    assert response_data[0]["currency"] == payload["currency"]
    assert response_data[0]["period"] == payload["period"]
    assert response_data[0]["start_date"] == payload["start_date"]
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
        "user_id": user_id,
        "category_id": None,
        "name": "Invalid budget",
        "limit_amount": 0,
        "currency": "EUR",
        "period": "monthly",
        "start_date": "2026-05-01",
        "end_date": None,
    }

    # Act
    response = client.post("/api/v1/budgets", json=payload)

    # Assert
    assert response.status_code == 422