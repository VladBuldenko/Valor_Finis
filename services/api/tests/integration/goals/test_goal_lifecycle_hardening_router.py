from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.modules.goals import goal_transaction_repository
from tests.helpers import auth_headers, create_goal, create_goal_transaction


def _seed_opening_balance(goal_id: str, user_id: str, amount: str = "300.00") -> None:
    db_session = SessionLocal()
    try:
        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal_id,
            user_id=user_id,
            type="opening_balance",
            amount=Decimal(amount),
            description=None,
        )
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Currency immutability
# ------------------------------------------------------------------


# Tests that PATCH can change currency on a goal with no transaction
# history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response reflects the new currency.
def test_patch_goal_endpoint_currency_change_allowed_without_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"currency": "USD"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["currency"] == "USD"


# Tests that PATCH rejects an actual currency change once transaction
# history exists, with a stable 409 detail message.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409 with the expected detail.
def test_patch_goal_endpoint_currency_change_rejected_with_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act
    response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"currency": "USD"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Goal currency cannot be changed after transaction history exists."
    )


# Tests that PATCH allows resending the same normalized currency after
# history exists.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 200, not 409.
def test_patch_goal_endpoint_same_normalized_currency_allowed_with_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act: EUR is the goal's default currency; lowercase must still
    # normalize to a no-op.
    response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"currency": "eur"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["currency"] == "EUR"


# Tests that archiving (PATCH status="archived") still works for a goal
# with transaction history, unaffected by the currency-immutability rule.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the archive PATCH succeeds.
def test_patch_goal_endpoint_archive_works_with_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act
    response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"status": "archived"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


# ------------------------------------------------------------------
# Safe delete
# ------------------------------------------------------------------


# Tests that DELETE succeeds for a goal with no transaction history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 204 and the goal is gone.
def test_delete_goal_endpoint_succeeds_without_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    response = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))

    # Assert
    assert response.status_code == 204

    get_response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    assert get_response.json() == []


# Tests that DELETE is rejected with 409 for a goal with contribution
# history, and that the detail message is stable and does not leak a raw
# database exception.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409 with the expected detail,
#   never a 500.
def test_delete_goal_endpoint_rejected_with_contribution_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act
    response = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Goal with transaction history cannot be deleted. Archive it instead."
    )

    get_response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    assert len(get_response.json()) == 1


# Tests that DELETE is rejected with 409 for a goal whose only history is
# a migration-created opening_balance row.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409.
def test_delete_goal_endpoint_rejected_with_opening_balance(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    _seed_opening_balance(goal["id"], user_id)

    # Act
    response = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))

    # Assert
    assert response.status_code == 409


# Tests that DELETE is rejected with 409 for a zero-balance goal (fully
# withdrawn) - balance must never be used as a proxy for "no history".
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409 despite a 0.00 balance.
def test_delete_goal_endpoint_rejected_with_zero_balance_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=60)
    create_goal_transaction(
        client=client, user_id=user_id, goal_id=goal["id"], amount=60, type="withdrawal",
    )

    # Act
    response = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))

    # Assert
    assert response.status_code == 409


# Tests that DELETE on another user's goal behaves as not found.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 404.
def test_delete_goal_endpoint_other_user_goal_returns_404(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    other_goal = create_goal(
        client=client, user_id=other_user_id, name="Car", target_amount=10000,
    )

    # Act
    response = client.delete(
        f"/api/v1/goals/{other_goal['id']}", headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."
