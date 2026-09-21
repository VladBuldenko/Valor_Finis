from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_goal, create_goal_transaction


# Tests that the API creates a contribution transaction successfully.
# This test exists to verify the full request flow: router -> auth
# dependency -> service -> repository -> PostgreSQL for the new POST
# transactions endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_goal_transaction_endpoint_creates_contribution(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    response = client.post(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"type": "contribution", "amount": 150, "description": "Payday"},
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["goal_id"] == goal["id"]
    assert response_data["user_id"] == user_id
    assert response_data["type"] == "contribution"
    assert response_data["amount"] == "150.00"
    assert response_data["description"] == "Payday"
    assert "id" in response_data
    assert "created_at" in response_data


# Tests that the API creates a withdrawal transaction successfully.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the withdrawal is created and the Goal's
#   current_amount reflects the reduced balance.
def test_create_goal_transaction_endpoint_creates_withdrawal(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=200)

    # Act
    response = client.post(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"type": "withdrawal", "amount": 80},
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["type"] == "withdrawal"
    assert response_data["amount"] == "80.00"

    goal_get_response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    updated_goal = next(g for g in goal_get_response.json() if g["id"] == goal["id"])
    assert updated_goal["current_amount"] == "120.00"


# Tests that a withdrawal exceeding the current balance is rejected with 409.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns conflict status code.
def test_create_goal_transaction_endpoint_insufficient_withdrawal_returns_409(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act
    response = client.post(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"type": "withdrawal", "amount": 50.01},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Withdrawal exceeds the current goal balance."


# Tests that a client cannot create an opening_balance transaction.
# This test exists because opening_balance is reserved for migration/system
# backfill (VF-016) - a client request must be rejected before it ever
# reaches the service layer.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_goal_transaction_endpoint_rejects_opening_balance(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    response = client.post(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"type": "opening_balance", "amount": 500},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that creating a transaction for another user's Goal behaves as not
# found.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_create_goal_transaction_endpoint_other_user_goal_returns_404(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    other_user_goal = create_goal(
        client=client, user_id=other_user_id, name="Car", target_amount=10000,
    )

    # Act
    response = client.post(
        f"/api/v1/goals/{other_user_goal['id']}/transactions",
        json={"type": "contribution", "amount": 100},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."


# Tests that creating a transaction without authentication is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_create_goal_transaction_endpoint_rejects_missing_auth(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.post(
        f"/api/v1/goals/{uuid4()}/transactions",
        json={"type": "contribution", "amount": 100},
    )

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."


# Tests that GET transaction history returns 200 with the created
# transactions.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if history contains the created transactions,
#   newest first.
def test_get_goal_transactions_endpoint_returns_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=100)
    create_goal_transaction(
        client=client, user_id=user_id, goal_id=goal["id"], amount=30, type="withdrawal",
    )

    # Act
    response = client.get(
        f"/api/v1/goals/{goal['id']}/transactions",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 2
    # Newest first: created_at DESC, id DESC - the withdrawal was created
    # after the contribution.
    assert response_data[0]["type"] == "withdrawal"
    assert response_data[1]["type"] == "contribution"


# Tests that reading transaction history for another user's Goal behaves as
# not found.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_get_goal_transactions_endpoint_other_user_goal_returns_404(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    other_user_goal = create_goal(
        client=client, user_id=other_user_id, name="Car", target_amount=10000,
    )

    # Act
    response = client.get(
        f"/api/v1/goals/{other_user_goal['id']}/transactions",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."


# Tests that reading transaction history without authentication is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_goal_transactions_endpoint_rejects_missing_auth(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(f"/api/v1/goals/{uuid4()}/transactions")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."


# Tests that there is no public mutation API for existing transactions.
# This test exists to verify append-only semantics at the router level:
# PATCH/DELETE on the transactions collection path must not be handled by
# any route, since transactions are never edited or deleted (VF-016).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both methods are rejected as not allowed.
def test_goal_transactions_endpoint_has_no_mutation_methods(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    patch_response = client.patch(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"amount": 1},
        headers=auth_headers(user_id),
    )
    delete_response = client.delete(
        f"/api/v1/goals/{goal['id']}/transactions",
        headers=auth_headers(user_id),
    )

    # Assert
    assert patch_response.status_code == 405
    assert delete_response.status_code == 405
