from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_goal


# Tests that the API creates a new financial goal successfully.
# This test exists to verify the full request flow: router -> auth dependency -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_goal_endpoint_creates_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "name": "Vacation",
        "target_amount": 2000,
        "current_amount": 500,
        "currency": "EUR",
        "target_date": "2026-12-31",
        "status": "active",
    }

    # Act
    response = client.post(
        "/api/v1/goals",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["user_id"] == user_id
    assert response_data["name"] == payload["name"]
    assert response_data["target_amount"] == "2000.00"
    assert response_data["current_amount"] == "500.00"
    assert response_data["currency"] == payload["currency"]
    assert response_data["target_date"] == payload["target_date"]
    assert response_data["status"] == payload["status"]
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the API returns goals for the authenticated user only.
# This test exists to verify that saved goals are filtered by the user resolved from authentication data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains only the authenticated user's goal.
def test_get_goals_endpoint_returns_authenticated_user_goals(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )
    create_goal(
        client=client,
        user_id=other_user_id,
        name="Car",
        target_amount=10000,
        current_amount=1000,
    )

    # Act
    response = client.get(
        "/api/v1/goals",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["name"] == "Vacation"
    assert response_data[0]["target_amount"] == "2000.00"
    assert response_data[0]["current_amount"] == "500.00"
    assert response_data[0]["currency"] == "EUR"
    assert response_data[0]["target_date"] == "2026-12-31"
    assert response_data[0]["status"] == "active"


# Tests that the API rejects a goal with zero target amount.
# This test exists to verify that request validation works before database persistence.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_goal_endpoint_rejects_zero_target_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "name": "Vacation",
        "target_amount": 0,
        "current_amount": 500,
        "currency": "EUR",
        "target_date": "2026-12-31",
        "status": "active",
    }

    # Act
    response = client.post(
        "/api/v1/goals",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects a goal when current amount is greater than target amount.
# This test exists to verify that logically invalid goal amounts are rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_goal_endpoint_rejects_current_amount_greater_than_target_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "name": "Vacation",
        "target_amount": 2000,
        "current_amount": 2500,
        "currency": "EUR",
        "target_date": "2026-12-31",
        "status": "active",
    }

    # Act
    response = client.post(
        "/api/v1/goals",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects requests without authentication header.
# This test exists to verify that the temporary auth dependency protects the goals endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_goals_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/goals")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-User-Id header."

# Tests that the API updates an authenticated user's financial goal.
# This test exists to verify the PATCH flow: router -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains updated goal data.
def test_update_goal_endpoint_updates_authenticated_user_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_goal = create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )

    payload = {
        "current_amount": 750,
        "status": "active",
    }

    # Act
    response = client.patch(
        f"/api/v1/goals/{created_goal['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["id"] == created_goal["id"]
    assert response_data["user_id"] == user_id
    assert response_data["name"] == "Vacation"
    assert response_data["target_amount"] == "2000.00"
    assert response_data["current_amount"] == "750.00"
    assert response_data["currency"] == "EUR"
    assert response_data["target_date"] == "2026-12-31"
    assert response_data["status"] == "active"


# Tests that the API rejects updating another user's financial goal.
# This test exists to verify ownership protection for PATCH requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_update_goal_endpoint_rejects_other_user_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_goal = create_goal(
        client=client,
        user_id=other_user_id,
        name="Car",
        target_amount=10000,
        current_amount=1000,
    )

    payload = {
        "current_amount": 1500,
    }

    # Act
    response = client.patch(
        f"/api/v1/goals/{other_user_goal['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."


# Tests that the API rejects empty goal update payloads.
# This test exists to verify that PATCH requests must contain at least one editable field.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_goal_endpoint_rejects_empty_payload(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_goal = create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )

    # Act
    response = client.patch(
        f"/api/v1/goals/{created_goal['id']}",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects goal updates where current amount becomes greater than target amount.
# This test exists to verify final amount validation after applying PATCH data to existing database data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns bad request status code.
def test_update_goal_endpoint_rejects_current_amount_greater_than_target_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_goal = create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )

    payload = {
        "current_amount": 2500,
    }

    # Act
    response = client.patch(
        f"/api/v1/goals/{created_goal['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "current_amount must be less than or equal to target_amount."
    )


# Tests that the API deletes an authenticated user's financial goal.
# This test exists to verify the DELETE flow and that deleted goals no longer appear in the list.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns no content and the goal is removed.
def test_delete_goal_endpoint_deletes_authenticated_user_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_goal = create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )

    # Act
    delete_response = client.delete(
        f"/api/v1/goals/{created_goal['id']}",
        headers=auth_headers(user_id),
    )

    get_response = client.get(
        "/api/v1/goals",
        headers=auth_headers(user_id),
    )

    # Assert
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert get_response.status_code == 200
    assert get_response.json() == []


# Tests that the API rejects deleting another user's financial goal.
# This test exists to verify ownership protection for DELETE requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_delete_goal_endpoint_rejects_other_user_goal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_goal = create_goal(
        client=client,
        user_id=other_user_id,
        name="Car",
        target_amount=10000,
        current_amount=1000,
    )

    # Act
    response = client.delete(
        f"/api/v1/goals/{other_user_goal['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."