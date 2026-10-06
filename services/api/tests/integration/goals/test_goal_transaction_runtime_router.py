from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.goals import goal_service
from tests.helpers import auth_headers, create_goal, create_goal_transaction

# VF-020B3 API tests for goal transaction runtime fields and create
# idempotency. The server date is pinned by replacing goal_service.date with
# a date subclass whose today() is frozen (the _FrozenDate pattern), so no
# assertion depends on the wall clock or on running near midnight.

MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)


def _freeze_today(monkeypatch, frozen_today: date) -> None:
    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return frozen_today

    monkeypatch.setattr(goal_service, "date", _FrozenDate)


def _post(client: TestClient, user_id: str, goal_id: str, body: dict):
    return client.post(
        f"/api/v1/goals/{goal_id}/transactions",
        json=body,
        headers=auth_headers(user_id),
    )


def _history(client: TestClient, user_id: str, goal_id: str) -> list:
    response = client.get(f"/api/v1/goals/{goal_id}/transactions", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return response.json()


def _archive(client: TestClient, user_id: str, goal_id: str) -> None:
    response = client.patch(
        f"/api/v1/goals/{goal_id}", json={"status": "archived"}, headers=auth_headers(user_id),
    )
    assert response.status_code == 200, response.text


# Tests that a new contribution returns 201 and exposes the runtime fields:
# the goal's currency, the server date and no key.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to pin the server date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response carries the expected fields.
def test_create_contribution_returns_201_with_runtime_fields(
    client: TestClient,
    monkeypatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch, MONDAY)
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)

    response = _post(client, user_id, goal["id"], {"type": "contribution", "amount": 150})

    assert response.status_code == 201
    body = response.json()
    assert body["currency"] == "EUR"
    assert body["effective_date"] == "2026-10-05"
    assert body["client_request_id"] is None


# Tests that a new withdrawal with a key returns 201 and echoes the key.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the withdrawal is created with its key.
def test_create_withdrawal_with_key_returns_201(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=200)
    key = str(uuid4())

    response = _post(
        client, user_id, goal["id"],
        {"type": "withdrawal", "amount": "80.00", "client_request_id": key},
    )

    assert response.status_code == 201
    assert response.json()["client_request_id"] == key
    assert response.json()["currency"] == "EUR"


# Tests that explicit today and past dates are accepted and returned.
# Parameters:
# - requested: effective_date sent with the request.
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to pin the server date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the requested date is stored.
@pytest.mark.parametrize("requested", ["2026-10-05", "2026-09-28"])
def test_today_and_past_effective_dates_return_201(
    requested: str,
    client: TestClient,
    monkeypatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch, MONDAY)
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)

    response = _post(
        client, user_id, goal["id"],
        {"type": "contribution", "amount": 10, "effective_date": requested},
    )

    assert response.status_code == 201
    assert response.json()["effective_date"] == requested


# Tests that a new request with tomorrow's date is rejected with 422 and
# nothing is written - without a key and with a key that is not used yet.
# Parameters:
# - extra: key field of the request (none, or a fresh unused key).
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to pin the server date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the request is rejected and history is empty.
@pytest.mark.parametrize(
    "extra", [{}, {"client_request_id": str(uuid4())}], ids=["no-key", "free-key"],
)
def test_future_effective_date_returns_422(
    extra: dict,
    client: TestClient,
    monkeypatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch, MONDAY)
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)

    response = _post(
        client, user_id, goal["id"],
        {"type": "contribution", "amount": 10, "effective_date": "2026-10-06", **extra},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Goal transaction effective date cannot be in the future."
    assert _history(client, user_id, goal["id"]) == []


# Tests that malformed request values are 422: a datetime instead of a date,
# a malformed key, and a client-chosen currency.
# Parameters:
# - extra: request fields that make the request invalid.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the request is rejected.
@pytest.mark.parametrize(
    "extra",
    [
        {"effective_date": "2026-10-05T00:00:00Z"},
        {"client_request_id": "not-a-uuid"},
        {"currency": "USD"},
    ],
    ids=["datetime", "malformed-key", "client-currency"],
)
def test_malformed_runtime_fields_return_422(
    extra: dict,
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)

    response = _post(client, user_id, goal["id"], {"type": "contribution", "amount": 10, **extra})

    assert response.status_code == 422
    assert _history(client, user_id, goal["id"]) == []


# Tests the idempotency statuses: the first keyed request is 201, an exact
# replay (with an equivalent decimal amount) is 200 with the same body, a
# different payload is 409, and only one row exists.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the statuses and the history match.
def test_keyed_create_replay_and_conflict_statuses(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    key = str(uuid4())
    body = {"type": "contribution", "amount": "10.00", "description": "Payday", "client_request_id": key}

    first = _post(client, user_id, goal["id"], body)
    replay = _post(client, user_id, goal["id"], {**body, "amount": 10})
    conflict = _post(client, user_id, goal["id"], {**body, "amount": 11})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "client_request_id has already been used for a different goal transaction."
    )
    assert [t["id"] for t in _history(client, user_id, goal["id"])] == [first.json()["id"]]


# Tests the date rules of a key that is already bound (VF-020B3 M1): on
# the next day, a replay stating the stored date is 200, while a replay
# stating a different date that is also in the future is 409 - the bound
# key answers for its original payload before any date validation - and
# only the original row exists.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to pin the server date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the statuses and the history match.
def test_bound_key_explicit_dates_replay_200_or_conflict_409(
    client: TestClient,
    monkeypatch,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    body = {"type": "contribution", "amount": 25, "client_request_id": str(uuid4())}

    _freeze_today(monkeypatch, MONDAY)
    first = _post(client, user_id, goal["id"], body)
    _freeze_today(monkeypatch, TUESDAY)
    same_date = _post(client, user_id, goal["id"], {**body, "effective_date": "2026-10-05"})
    future_date = _post(client, user_id, goal["id"], {**body, "effective_date": "2026-10-07"})

    assert first.status_code == 201
    assert same_date.status_code == 200
    assert same_date.json()["id"] == first.json()["id"]
    assert future_date.status_code == 409
    assert future_date.json()["detail"] == (
        "client_request_id has already been used for a different goal transaction."
    )
    assert [t["id"] for t in _history(client, user_id, goal["id"])] == [first.json()["id"]]


# Tests that a replay sent the next day without effective_date returns 200
# and the original transaction with its original date.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to pin the server date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the Tuesday replay returns the Monday row.
def test_replay_after_midnight_without_date_returns_200(
    client: TestClient,
    monkeypatch,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    body = {"type": "contribution", "amount": 25, "client_request_id": str(uuid4())}

    _freeze_today(monkeypatch, MONDAY)
    first = _post(client, user_id, goal["id"], body)
    _freeze_today(monkeypatch, TUESDAY)
    replay = _post(client, user_id, goal["id"], body)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["effective_date"] == "2026-10-05"


# Tests the archived-goal ordering: a replay of a contribution made before
# archiving is 200, while a contribution with a fresh key is 409.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the replay succeeds and the new key fails.
def test_archived_goal_replay_200_and_fresh_contribution_409(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    body = {"type": "contribution", "amount": 50, "client_request_id": str(uuid4())}
    first = _post(client, user_id, goal["id"], body)
    _archive(client, user_id, goal["id"])

    replay = _post(client, user_id, goal["id"], body)
    fresh = _post(client, user_id, goal["id"], {**body, "client_request_id": str(uuid4())})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert fresh.status_code == 409
    assert fresh.json()["detail"] == "Archived goal cannot receive contributions."


# Tests that another user's key and goal never reveal their transaction:
# the request is 404, exactly like any foreign goal.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the intruder gets 404.
def test_other_users_replay_returns_404(client: TestClient, clean_database: None) -> None:
    owner = str(uuid4())
    intruder = str(uuid4())
    goal = create_goal(client=client, user_id=owner)
    body = {"type": "contribution", "amount": 50, "client_request_id": str(uuid4())}
    assert _post(client, owner, goal["id"], body).status_code == 201

    response = _post(client, intruder, goal["id"], body)

    assert response.status_code == 404
    assert response.json()["detail"] == "Goal not found."


# Tests that GET history serializes a row written before VF-020B3 with
# currency, effective_date and client_request_id all NULL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the legacy row is returned with nulls.
def test_history_serializes_legacy_null_runtime_fields(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client=client, user_id=user_id)
    db_session = SessionLocal()
    try:
        db_session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount) "
                "VALUES (:id, :goal_id, :user_id, 'opening_balance', 200)"
            ),
            {"id": str(uuid4()), "goal_id": goal["id"], "user_id": user_id},
        )
        db_session.commit()
    finally:
        db_session.close()

    history = _history(client, user_id, goal["id"])

    assert len(history) == 1
    assert history[0]["type"] == "opening_balance"
    assert (history[0]["currency"], history[0]["effective_date"], history[0]["client_request_id"]) == (
        None, None, None,
    )
