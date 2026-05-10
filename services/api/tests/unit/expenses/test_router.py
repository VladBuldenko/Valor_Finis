from fastapi.testclient import TestClient

from app.main import app
from app.modules.expenses import repository


client = TestClient(app)


# Resets the in-memory expense repository state before each test.
# This helper exists to keep API integration tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    repository.expenses_storage.clear()
    repository.next_expense_id = 1


# Tests that the API creates a new expense successfully.
# This test exists to verify the full request flow: router → service → repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_expense_endpoint_creates_expense() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "amount": 24.99,
        "category": "food",
        "description": "Lidl groceries",
        "date": "2026-05-07",
    }

    # Act
    response = client.post("/api/v1/expenses", json=payload)

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["id"] == 1
    assert response_data["amount"] == "24.99"
    assert response_data["category"] == "food"
    assert response_data["description"] == "Lidl groceries"
    assert response_data["date"] == "2026-05-07"
    assert "created_at" in response_data


# Tests that the API returns all created expenses.
# This test exists to verify that saved expenses can be retrieved through the endpoint.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response contains the created expense.
def test_get_expenses_endpoint_returns_expenses() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "amount": 24.99,
        "category": "food",
        "description": "Lidl groceries",
        "date": "2026-05-07",
    }

    client.post("/api/v1/expenses", json=payload)

    # Act
    response = client.get("/api/v1/expenses")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["id"] == 1
    assert response_data[0]["amount"] == "24.99"
    assert response_data[0]["category"] == "food"


# Tests that the API rejects an expense with zero amount.
# This test exists to verify that request validation works through the API layer.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_expense_endpoint_rejects_zero_amount() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "amount": 0,
        "category": "food",
        "description": "Invalid expense",
        "date": "2026-05-07",
    }

    # Act
    response = client.post("/api/v1/expenses", json=payload)

    # Assert
    assert response.status_code == 422