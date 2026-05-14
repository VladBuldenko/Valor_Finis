from fastapi.testclient import TestClient

from app.main import app
from app.modules.goals import goal_repository


client = TestClient(app)


# Resets the in-memory goal repository state before each test.
# This helper exists to keep API integration tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    goal_repository.goals_storage.clear()
    goal_repository.next_goal_id = 1


# Tests that the API creates a new financial goal successfully.
# This test exists to verify the full request flow: router → service → repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_goal_endpoint_creates_goal() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "name": "Vacation",
        "target_amount": 2000,
        "current_amount": 500,
        "deadline": "2026-12-31",
    }

    # Act
    response = client.post("/api/v1/goals", json=payload)

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["id"] == 1
    assert response_data["name"] == "Vacation"
    assert response_data["target_amount"] == "2000"
    assert response_data["current_amount"] == "500"
    assert response_data["deadline"] == "2026-12-31"
    assert "created_at" in response_data


# Tests that the API returns all created financial goals.
# This test exists to verify that saved goals can be retrieved through the endpoint.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response contains the created goal.
def test_get_goals_endpoint_returns_goals() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "name": "Vacation",
        "target_amount": 2000,
        "current_amount": 500,
        "deadline": "2026-12-31",
    }

    client.post("/api/v1/goals", json=payload)

    # Act
    response = client.get("/api/v1/goals")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["id"] == 1
    assert response_data[0]["name"] == "Vacation"


# Tests that the API rejects a goal with zero target amount.
# This test exists to verify that request validation works through the API layer.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_goal_endpoint_rejects_zero_target_amount() -> None:
    # Arrange
    reset_repository_state()

    payload = {
        "name": "Vacation",
        "target_amount": 0,
        "current_amount": 500,
        "deadline": "2026-12-31",
    }

    # Act
    response = client.post("/api/v1/goals", json=payload)

    # Assert
    assert response.status_code == 422