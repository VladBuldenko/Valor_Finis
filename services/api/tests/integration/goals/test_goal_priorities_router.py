from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.goals import goal_user_lock
from tests.helpers import auth_headers, create_account

# VF-020D3 API tests: priority_rank lifecycle, canonical GET order, the
# reorder endpoint (PUT /api/v1/goals/priorities) and the L0 coverage of
# every Goal write. Rank-NULL "rollout stragglers" (non-archived Goals
# created between the D2 migration and the D3 runtime) are produced with raw
# SQL, exactly the shape the previous runtime left behind.


def _create(client: TestClient, user_id: str, name: str = "Goal", status: str = "active", **extra: Any) -> dict:
    response = client.post(
        "/api/v1/goals",
        json={"name": name, "target_amount": 1000, "currency": "EUR", "status": status, **extra},
        headers=auth_headers(user_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _list(client: TestClient, user_id: str) -> list:
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return response.json()


def _ranks(client: TestClient, user_id: str) -> dict:
    return {goal["id"]: goal["priority_rank"] for goal in _list(client, user_id)}


def _patch(client: TestClient, user_id: str, goal_id: str, body: dict):
    return client.patch(f"/api/v1/goals/{goal_id}", json=body, headers=auth_headers(user_id))


def _reorder(client: TestClient, user_id: str, goal_ids: list):
    return client.put(
        "/api/v1/goals/priorities", json={"goal_ids": goal_ids}, headers=auth_headers(user_id),
    )


def _make_straggler(goal_id: str) -> None:
    with SessionLocal() as session:
        session.execute(text("UPDATE goals SET priority_rank = NULL WHERE id = :id"), {"id": goal_id})
        session.commit()


def _insert_goal(user_id: str, status: str, created_at: datetime, goal_id: Optional[UUID] = None, rank: Optional[int] = None) -> str:
    goal_id = goal_id or uuid4()
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status, created_at, priority_rank) "
                "VALUES (:id, :u, 'Raw', 100, 'EUR', :s, :c, :r)"
            ),
            {"id": str(goal_id), "u": user_id, "s": status, "c": created_at, "r": rank},
        )
        session.commit()
    return str(goal_id)


def _count(table: str, user_id: str) -> int:
    with SessionLocal() as session:
        return session.execute(
            text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": user_id},
        ).scalar_one()


# ------------------------------------------------------------------
# Rank lifecycle
# ------------------------------------------------------------------


def test_new_active_and_completed_goals_are_appended_last_and_archived_is_null(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    first = _create(client, user_id, "A", "active")
    second = _create(client, user_id, "B", "completed")
    archived = _create(client, user_id, "C", "archived")
    third = _create(client, user_id, "D", "active")

    assert first["priority_rank"] == 1
    assert second["priority_rank"] == 2
    assert archived["priority_rank"] is None
    assert third["priority_rank"] == 3


def test_active_completed_toggle_preserves_rank_and_archive_clears_without_compaction(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    one, two, three, four = (_create(client, user_id, name)["id"] for name in "ABCD")

    assert _patch(client, user_id, two, {"status": "completed"}).json()["priority_rank"] == 2
    assert _patch(client, user_id, two, {"status": "active"}).json()["priority_rank"] == 2
    assert _patch(client, user_id, two, {"status": "archived"}).json()["priority_rank"] is None

    ranks = _ranks(client, user_id)
    assert ranks == {one: 1, two: None, three: 3, four: 4}  # a gap, no compaction


def test_reactivation_appends_last_for_active_and_completed(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    one, two, three = (_create(client, user_id, name)["id"] for name in "ABC")
    assert _patch(client, user_id, one, {"status": "archived"}).status_code == 200
    assert _patch(client, user_id, two, {"status": "archived"}).status_code == 200

    back_active = _patch(client, user_id, one, {"status": "active"})
    back_completed = _patch(client, user_id, two, {"status": "completed"})

    assert back_active.json()["priority_rank"] == 4   # max(3) + 1
    assert back_completed.json()["priority_rank"] == 5
    assert _ranks(client, user_id)[three] == 3


def test_non_status_edit_preserves_rank_and_delete_leaves_a_gap(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    one, two, three = (_create(client, user_id, name)["id"] for name in "ABC")

    renamed = _patch(client, user_id, two, {"name": "Renamed", "target_amount": "1500.00"})
    assert renamed.json()["priority_rank"] == 2

    assert client.delete(f"/api/v1/goals/{two}", headers=auth_headers(user_id)).status_code == 204
    assert _ranks(client, user_id) == {one: 1, three: 3}

    fourth = _create(client, user_id, "D")
    assert fourth["priority_rank"] == 4


def test_unrelated_edit_does_not_rank_a_rollout_straggler(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    ranked = _create(client, user_id, "Ranked")["id"]
    straggler = _create(client, user_id, "Straggler")["id"]
    _make_straggler(straggler)

    edited = _patch(client, user_id, straggler, {"name": "Edited"})
    toggled = _patch(client, user_id, straggler, {"status": "completed"})

    assert edited.json()["priority_rank"] is None
    assert toggled.json()["priority_rank"] is None
    assert _ranks(client, user_id) == {ranked: 1, straggler: None}


@pytest.mark.parametrize("verb", ["post", "patch"])
def test_client_cannot_write_priority_rank(client: TestClient, clean_database: None, verb: str) -> None:
    user_id = str(uuid4())
    goal = _create(client, user_id)

    if verb == "post":
        response = client.post(
            "/api/v1/goals",
            json={"name": "X", "target_amount": 10, "currency": "EUR", "priority_rank": 1},
            headers=auth_headers(user_id),
        )
    else:
        response = _patch(client, user_id, goal["id"], {"priority_rank": 1})

    assert response.status_code == 422


def test_response_paths_expose_priority_rank(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    created = _create(client, user_id)

    assert created["priority_rank"] == 1
    assert _patch(client, user_id, created["id"], {"name": "N"}).json()["priority_rank"] == 1
    assert _list(client, user_id)[0]["priority_rank"] == 1


# ------------------------------------------------------------------
# Canonical order
# ------------------------------------------------------------------


# Tests the exact canonical GET order: ranked by rank ASC, then non-archived
# rank-NULL stragglers by created_at ASC / id ASC, then archived by
# created_at DESC / id ASC, with equal timestamps resolved by id.
def test_canonical_order_mixes_ranked_stragglers_and_archived(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    same = datetime(2026, 3, 1, tzinfo=timezone.utc)
    low, high = UUID(int=2), UUID(int=9)

    ranked_second = _insert_goal(user_id, "completed", datetime(2026, 1, 1, tzinfo=timezone.utc), rank=2)
    ranked_first = _insert_goal(user_id, "active", datetime(2026, 5, 1, tzinfo=timezone.utc), rank=1)
    straggler_late = _insert_goal(user_id, "active", datetime(2026, 4, 1, tzinfo=timezone.utc))
    straggler_tie_high = _insert_goal(user_id, "completed", same, goal_id=high)
    straggler_tie_low = _insert_goal(user_id, "active", same, goal_id=low)
    archived_old = _insert_goal(user_id, "archived", datetime(2026, 1, 1, tzinfo=timezone.utc))
    archived_new_high = _insert_goal(user_id, "archived", datetime(2026, 6, 1, tzinfo=timezone.utc), goal_id=UUID(int=20))
    archived_new_low = _insert_goal(user_id, "archived", datetime(2026, 6, 1, tzinfo=timezone.utc), goal_id=UUID(int=10))

    order = [goal["id"] for goal in _list(client, user_id)]

    assert order == [
        ranked_first, ranked_second,
        straggler_tie_low, straggler_tie_high, straggler_late,
        archived_new_low, archived_new_high, archived_old,
    ]


# ------------------------------------------------------------------
# Reorder
# ------------------------------------------------------------------


def test_route_is_reachable_and_not_captured_by_goal_id(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = _create(client, user_id)

    response = _reorder(client, user_id, [goal["id"]])

    assert response.status_code == 200, response.text
    # A request that reached the dynamic /{goal_id} route would be a 422
    # ("priorities" is not a UUID) or 405, never a list of Goals.
    assert isinstance(response.json(), list)


def test_valid_reorder_rewrites_1_to_n_and_returns_canonical_list_with_archived(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    a, b, c = (_create(client, user_id, name)["id"] for name in "ABC")
    archived = _create(client, user_id, "Arch", "archived")["id"]
    assert _patch(client, user_id, b, {"status": "completed"}).status_code == 200

    response = _reorder(client, user_id, [c, a, b])

    assert response.status_code == 200, response.text
    body = response.json()
    assert [goal["id"] for goal in body] == [c, a, b, archived]
    assert [goal["priority_rank"] for goal in body] == [1, 2, 3, None]
    assert _list(client, user_id) == body  # same canonical order as GET


def test_same_order_again_is_200_and_one_goal_is_200(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    only = _create(client, user_id)["id"]

    first = _reorder(client, user_id, [only])
    second = _reorder(client, user_id, [only])

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()


def test_gaps_are_rewritten_to_a_dense_sequence(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    one, two, three = (_create(client, user_id, name)["id"] for name in "ABC")
    assert client.delete(f"/api/v1/goals/{two}", headers=auth_headers(user_id)).status_code == 204

    response = _reorder(client, user_id, [three, one])

    assert [goal["priority_rank"] for goal in response.json()] == [1, 2]


def test_duplicate_and_malformed_ids_are_422(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = _create(client, user_id)["id"]

    assert _reorder(client, user_id, [goal, goal]).status_code == 422
    assert _reorder(client, user_id, ["not-a-uuid"]).status_code == 422
    extra = client.put(
        "/api/v1/goals/priorities", json={"goal_ids": [goal], "x": 1}, headers=auth_headers(user_id),
    )
    assert extra.status_code == 422


def test_foreign_and_nonexistent_ids_are_the_same_404(client: TestClient, clean_database: None) -> None:
    user_id, other_id = str(uuid4()), str(uuid4())
    mine = _create(client, user_id)["id"]
    foreign = _create(client, other_id)["id"]

    foreign_response = _reorder(client, user_id, [mine, foreign])
    missing_response = _reorder(client, user_id, [mine, str(uuid4())])

    assert foreign_response.status_code == 404 and missing_response.status_code == 404
    assert foreign_response.json() == missing_response.json() == {"detail": "Goal not found."}
    assert _ranks(client, other_id)[foreign] == 1  # nothing of the other user changed


def test_archived_supplied_is_409_and_precedence_is_404_then_archived_then_stale(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    active = _create(client, user_id, "A")["id"]
    _create(client, user_id, "B")  # omitted on purpose: would also be stale
    archived = _create(client, user_id, "Arch", "archived")["id"]

    archived_response = _reorder(client, user_id, [active, archived])
    both = _reorder(client, user_id, [str(uuid4()), archived])

    assert archived_response.status_code == 409
    assert archived_response.json()["detail"] == "Archived goals cannot be ranked."
    assert both.status_code == 404  # existence is established before the archived check


def test_missing_non_archived_goal_is_a_stale_409_and_changes_nothing(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    a, b = (_create(client, user_id, name)["id"] for name in "AB")
    before = _ranks(client, user_id)

    response = _reorder(client, user_id, [b])

    assert response.status_code == 409
    assert response.json()["detail"] == "Goal list is out of date. Reload goals and try again."
    assert _ranks(client, user_id) == before == {a: 1, b: 2}


def test_empty_list_is_200_only_without_non_archived_goals(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    assert _reorder(client, user_id, []).json() == []

    archived = _create(client, user_id, "Arch", "archived")["id"]
    only_archived = _reorder(client, user_id, [])
    assert only_archived.status_code == 200
    assert [goal["id"] for goal in only_archived.json()] == [archived]

    _create(client, user_id, "Active")
    assert _reorder(client, user_id, []).status_code == 409


def test_rollout_straggler_is_part_of_the_required_set_and_becomes_ranked(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    ranked = _create(client, user_id, "R")["id"]
    straggler = _create(client, user_id, "S")["id"]
    _make_straggler(straggler)

    missing_straggler = _reorder(client, user_id, [ranked])
    complete = _reorder(client, user_id, [straggler, ranked])

    assert missing_straggler.status_code == 409
    assert complete.status_code == 200
    assert _ranks(client, user_id) == {straggler: 1, ranked: 2}


def test_reorder_never_writes_ledgers_or_money_rows(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal_one = _create(client, user_id, "A")["id"]
    goal_two = _create(client, user_id, "B")["id"]
    contribution = client.post(
        f"/api/v1/goals/{goal_one}/transactions",
        json={"type": "contribution", "amount": "10.00"},
        headers=auth_headers(user_id),
    )
    assert contribution.status_code == 201
    tables = ("goal_transactions", "account_transactions", "income", "expenses", "account_transfers")
    before = {table: _count(table, user_id) for table in tables}

    assert _reorder(client, user_id, [goal_two, goal_one]).status_code == 200

    assert {table: _count(table, user_id) for table in tables} == before
    goal = next(item for item in _list(client, user_id) if item["id"] == goal_one)
    assert goal["current_amount"] == "10.00"


# ------------------------------------------------------------------
# L0 coverage of every Goal write (observed through the real service path)
# ------------------------------------------------------------------


@pytest.fixture
def l0_calls(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []
    original = goal_user_lock.acquire_goal_user_lock

    def recording(db_session, user_id):
        calls.append(user_id)
        return original(db_session, user_id)

    monkeypatch.setattr(goal_user_lock, "acquire_goal_user_lock", recording)
    return calls


def _tx(client: TestClient, user_id: str, goal_id: str, body: dict):
    return client.post(f"/api/v1/goals/{goal_id}/transactions", json=body, headers=auth_headers(user_id))


def test_every_goal_write_takes_l0_exactly_once(client: TestClient, clean_database: None, l0_calls: list) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, opening_balance="500.00")

    def took_l0(action) -> int:
        before = len(l0_calls)
        response = action()
        assert response.status_code in (200, 201, 204), response.text
        return len(l0_calls) - before

    created = {}

    def create_goal_action():
        response = client.post(
            "/api/v1/goals",
            json={"name": "G", "target_amount": 1000, "currency": "EUR"},
            headers=auth_headers(user_id),
        )
        created["goal"] = response.json()
        return response

    assert took_l0(create_goal_action) == 1
    goal_id = created["goal"]["id"]
    other = _create(client, user_id, "Other")["id"]

    assert took_l0(lambda: _patch(client, user_id, goal_id, {"name": "New name"})) == 1          # metadata
    assert took_l0(lambda: _tx(client, user_id, goal_id, {"type": "contribution", "amount": "100.00"})) == 1
    assert took_l0(lambda: _tx(client, user_id, goal_id, {"type": "withdrawal", "amount": "10.00"})) == 1
    assert took_l0(lambda: _tx(client, user_id, goal_id, {
        "type": "contribution", "amount": "50.00", "account_id": account["id"], "client_request_id": str(uuid4()),
    })) == 1                                                                                      # linked contribution
    assert took_l0(lambda: _tx(client, user_id, goal_id, {
        "type": "withdrawal", "amount": "5.00", "account_id": account["id"], "client_request_id": str(uuid4()),
    })) == 1                                                                                      # linked release
    assert took_l0(lambda: _patch(client, user_id, goal_id, {"status": "completed"})) == 1
    assert took_l0(lambda: _patch(client, user_id, goal_id, {"status": "active"})) == 1
    assert took_l0(lambda: _patch(client, user_id, goal_id, {"status": "archived"})) == 1
    assert took_l0(lambda: _patch(client, user_id, goal_id, {"status": "active"})) == 1          # reactivate
    assert took_l0(lambda: _reorder(client, user_id, [other, goal_id])) == 1
    assert took_l0(lambda: client.delete(f"/api/v1/goals/{other}", headers=auth_headers(user_id))) == 1
    assert set(l0_calls) == {UUID(user_id)}


def test_reads_replays_and_account_lifecycle_do_not_take_l0(
    client: TestClient, clean_database: None, l0_calls: list,
) -> None:
    user_id = str(uuid4())
    goal = _create(client, user_id)["id"]
    unused = create_account(client, user_id)
    key = str(uuid4())
    body = {"type": "contribution", "amount": "10.00", "client_request_id": key}
    assert _tx(client, user_id, goal, body).status_code == 201
    l0_calls.clear()

    assert client.get("/api/v1/goals", headers=auth_headers(user_id)).status_code == 200
    assert client.get(f"/api/v1/goals/{goal}/transactions", headers=auth_headers(user_id)).status_code == 200
    replay = _tx(client, user_id, goal, body)
    assert replay.status_code == 200
    conflict = _tx(client, user_id, goal, {**body, "amount": "11.00"})
    assert conflict.status_code == 409
    assert client.patch(
        f"/api/v1/accounts/{unused['id']}", json={"currency": "USD"}, headers=auth_headers(user_id),
    ).status_code == 200
    assert client.delete(f"/api/v1/accounts/{unused['id']}", headers=auth_headers(user_id)).status_code == 204

    assert l0_calls == []
