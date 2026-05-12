from fastapi.testclient import TestClient

from app.main import app
from app.modules.budgets import budget_repository


client = TestClient(app)


# Resets the in-memory budget repository state before each test.
# This helper exists to keep API integration tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    budget_repository.budgets_storage.clear()
    budget_repository.next_budget_id = 1


# Tests that the API creates a new budget limit successfully.
# This test exists to verify the full request flow: router → service → repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_budget_endpoint_creates_budget() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "category": "food",
        "monthly_limit": 400,
        "month": "2026-05-01",
    }

    # Act
    response = client.post("/api/v1/budgets", json=payload)

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["id"] == 1
    assert response_data["category"] == "food"
    assert response_data["monthly_limit"] == "400"
    assert response_data["month"] == "2026-05-01"
    assert "created_at" in response_data


# Tests that the API returns all created budget limits.
# This test exists to verify that saved budgets can be retrieved through the endpoint.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response contains the created budget.
def test_get_budgets_endpoint_returns_budgets() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "category": "food",
        "monthly_limit": 400,
        "month": "2026-05-01",
    }

    client.post("/api/v1/budgets", json=payload)

    # Act
    response = client.get("/api/v1/budgets")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["id"] == 1
    assert response_data[0]["category"] == "food"


# Tests that the API rejects a budget limit with zero monthly limit.
# This test exists to verify that request validation works through the API layer.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_budget_endpoint_rejects_zero_monthly_limit() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "category": "food",
        "monthly_limit": 0,
        "month": "2026-05-01",
    }

    # Act
    response = client.post("/api/v1/budgets", json=payload)

    # Assert
    assert response.status_code == 422