from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.modules.goals.goal_models import GoalModel
from tests.helpers import auth_headers, create_goal, create_goal_transaction


# Tests that GET /goals exposes a ledger-derived current_amount combining
# opening_balance, contribution, and withdrawal math through the real API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if current_amount matches the ledger sum exactly.
def test_get_goals_endpoint_exposes_ledger_derived_balance(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=200)
    create_goal_transaction(
        client=client, user_id=user_id, goal_id=goal["id"], amount=80, type="withdrawal",
    )

    # Act
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))

    # Assert
    assert response.status_code == 200
    assert response.json()[0]["current_amount"] == "120.00"


# Tests that a zero-transaction Goal remains present in GET /goals with a
# 0.00 balance.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the goal is present with current_amount 0.00.
def test_get_goals_endpoint_zero_transaction_goal_remains_present(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)

    # Act
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))

    # Assert
    response_data = response.json()
    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["current_amount"] == "0.00"


# Tests that another user's transactions never affect this user's Goal
# balance in GET /goals.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the authenticated user's ledger is used.
def test_get_goals_endpoint_other_user_ledger_does_not_leak(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=2000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=10)

    other_goal = create_goal(client=client, user_id=other_user_id, name="Car", target_amount=10000)
    create_goal_transaction(
        client=client, user_id=other_user_id, goal_id=other_goal["id"], amount=9999,
    )

    # Act
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))

    # Assert
    response_data = response.json()
    assert len(response_data) == 1
    assert response_data[0]["current_amount"] == "10.00"


# Tests the critical VF-016D invariant at the API level: when the
# transitional goals.current_amount column disagrees with the ledger, both
# GET /goals and PATCH /goals/{id} must return the ledger value, never the
# corrupted column.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both endpoints return 150.00, not 999.00.
def test_goal_endpoints_ignore_stale_current_amount_column(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=1000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=100)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Corrupt the transitional column directly, bypassing every
    # application write path.
    db_session = SessionLocal()
    try:
        goal_model = (
            db_session.query(GoalModel).filter(GoalModel.id == goal["id"]).first()
        )
        goal_model.current_amount = Decimal("999.00")
        db_session.commit()
    finally:
        db_session.close()

    # Act
    get_response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    patch_response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"name": "Renamed"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert get_response.json()[0]["current_amount"] == "150.00"
    assert patch_response.json()["current_amount"] == "150.00"
    assert patch_response.json()["name"] == "Renamed"


# Tests that GET /analytics/goal-progress exposes a ledger-derived balance
# through the real API, including remaining_amount and progress_percent
# computed from that same balance.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if all three fields reflect the ledger balance.
def test_goal_progress_endpoint_exposes_ledger_derived_balance(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=1000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=100)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    # Act
    response = client.get("/api/v1/analytics/goal-progress", headers=auth_headers(user_id))

    # Assert
    response_data = response.json()[0]
    assert response_data["current_amount"] == "150.00"
    assert response_data["remaining_amount"] == "850.00"
    assert response_data["progress_percent"] == "15.00"


# Tests that an overfunded Goal's progress_percent is not capped at 100.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if progress_percent is exactly 120.00 and
#   remaining_amount is floored at 0.
def test_goal_progress_endpoint_uncapped_overfunded_progress_percent(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=1000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=1200)

    # Act
    response = client.get("/api/v1/analytics/goal-progress", headers=auth_headers(user_id))

    # Assert
    response_data = response.json()[0]
    assert response_data["current_amount"] == "1200.00"
    # remaining_amount is floored via max(target - current, Decimal("0")):
    # when clamped, the literal Decimal("0") floor value is returned as-is,
    # which serializes as "0" rather than "0.00" - pre-existing formula
    # behavior, unrelated to VF-016D.
    assert response_data["remaining_amount"] == "0"
    assert response_data["progress_percent"] == "120.00"


# Tests the critical VF-016D invariant for Goal Progress: a stale
# goals.current_amount column must never leak into the analytics response.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response reflects the ledger (150.00),
#   not the corrupted column (999.00).
def test_goal_progress_endpoint_ignores_stale_current_amount_column(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id, name="Vacation", target_amount=1000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=100)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=50)

    db_session = SessionLocal()
    try:
        goal_model = (
            db_session.query(GoalModel).filter(GoalModel.id == goal["id"]).first()
        )
        goal_model.current_amount = Decimal("999.00")
        db_session.commit()
    finally:
        db_session.close()

    # Act
    response = client.get("/api/v1/analytics/goal-progress", headers=auth_headers(user_id))

    # Assert
    response_data = response.json()[0]
    assert response_data["current_amount"] == "150.00"
    assert response_data["remaining_amount"] == "850.00"
