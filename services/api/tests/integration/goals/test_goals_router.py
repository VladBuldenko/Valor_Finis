from fastapi.testclient import TestClient


# Tests that the API creates a new financial goal successfully.
# This test exists to verify the full request flow: router → service → repository → PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_goal_endpoint_creates_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
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
    assert response_data["name"] == "Vacation"
    assert response_data["target_amount"] == "2000.00"
    assert response_data["current_amount"] == "500.00"
    assert response_data["deadline"] == "2026-12-31"
    assert "id" in response_data
    assert "created_at" in response_data


# Tests that the API returns all created financial goals from PostgreSQL.
# This test exists to verify that saved goals can be retrieved through the endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before the test.
# Returns:
# - None. The test passes if the response contains the created goal.
def test_get_goals_endpoint_returns_goals(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
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
    assert response_data[0]["name"] == "Vacation"
    assert response_data[0]["target_amount"] == "2000.00"
    assert response_data[0]["current_amount"] == "500.00"


# Tests that the API rejects a goal with zero target amount.
# This test exists to verify that request validation works before database persistence.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_goal_endpoint_rejects_zero_target_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
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