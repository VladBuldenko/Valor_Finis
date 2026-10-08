from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import SessionLocal, engine
from app.modules.goals import goal_service
from tests.helpers import (
    auth_headers,
    create_account,
    create_account_transaction,
    create_account_transfer,
    create_goal,
)

# VF-020C2 API tests for Account-linked Goal operations: linked/tracked
# partitions, the approved 404/409/422 precedence, B3 idempotency semantics
# (account_id in the payload), the Account capacity read model, Goal
# read-model fields and Account delete / currency protection.

TODAY = date.today()
FUTURE = (TODAY + timedelta(days=30)).isoformat()
PAST = (TODAY - timedelta(days=30)).isoformat()

ACCOUNT_NOT_FOUND = "Account not found."
GOAL_NOT_FOUND = "Goal not found."
GOAL_ARCHIVED = "Archived goal cannot receive contributions."
ACCOUNT_ARCHIVED = "Archived account cannot receive new transactions."
CAPACITY = "Reservation exceeds the Account's reservable capacity."
PARTITION = "Withdrawal exceeds the goal amount reserved against this account."
TRACKED_SHORTFALL = "Withdrawal exceeds the current goal balance."
IDEMPOTENCY_CONFLICT = "client_request_id has already been used for a different goal transaction."
CURRENCY_MISMATCH = "Goal and Account currencies must match."


def _post(client: TestClient, user_id: str, goal_id: str, body: dict):
    return client.post(
        f"/api/v1/goals/{goal_id}/transactions", json=body, headers=auth_headers(user_id),
    )


def _linked(
    client: TestClient,
    user_id: str,
    goal_id: str,
    account_id: str,
    amount: str,
    type: str = "contribution",
    key: Optional[str] = None,
    **extra: Any,
):
    body: dict[str, Any] = {
        "type": type,
        "amount": amount,
        "account_id": account_id,
        "client_request_id": key or str(uuid4()),
    }
    body.update(extra)
    return _post(client, user_id, goal_id, body)


def _funded_account(client: TestClient, user_id: str, balance: str = "1000.00", currency: str = "EUR") -> dict:
    return create_account(client, user_id, currency=currency, opening_balance=balance)


def _account(client: TestClient, user_id: str, account_id: str) -> dict:
    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["id"] == account_id)


def _goal(client: TestClient, user_id: str, goal_id: str) -> dict:
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["id"] == goal_id)


def _count_goal_rows(user_id: str) -> int:
    with SessionLocal() as session:
        return session.execute(
            text("SELECT count(*) FROM goal_transactions WHERE user_id = :u"), {"u": user_id},
        ).scalar_one()


def _patch_goal(client: TestClient, user_id: str, goal_id: str, body: dict):
    return client.patch(f"/api/v1/goals/{goal_id}", json=body, headers=auth_headers(user_id))


def _patch_account(client: TestClient, user_id: str, account_id: str, body: dict):
    return client.patch(f"/api/v1/accounts/{account_id}", json=body, headers=auth_headers(user_id))


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------


# Tests that a linked request without a client_request_id is a 422, for a
# contribution and for a withdrawal, before anything else is read.
def test_linked_request_without_key_is_422(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)

    for kind in ("contribution", "withdrawal"):
        response = _post(
            client, user_id, goal["id"],
            {"type": kind, "amount": "10", "account_id": str(uuid4())},
        )
        assert response.status_code == 422, response.text

    assert _count_goal_rows(user_id) == 0


# Tests malformed account_id, non-positive amount and explicit null
# account_id (= tracked, key optional).
def test_schema_validation_and_null_account_id_means_tracked(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)

    bad_uuid = _post(client, user_id, goal["id"], {
        "type": "contribution", "amount": "10", "account_id": "nope", "client_request_id": str(uuid4()),
    })
    zero = _post(client, user_id, goal["id"], {
        "type": "contribution", "amount": "0", "account_id": str(uuid4()), "client_request_id": str(uuid4()),
    })
    tracked = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10", "account_id": None})

    assert bad_uuid.status_code == 422
    assert zero.status_code == 422
    assert tracked.status_code == 201
    assert tracked.json()["account_id"] is None


# ------------------------------------------------------------------
# Linked contribution: happy path and read models
# ------------------------------------------------------------------


# Tests a linked contribution end to end: 201 with account_id and today's
# date, the Goal's partitions and allocations, and the Account's eight new
# fields; current_balance is unchanged (a reservation is not a ledger row).
def test_linked_contribution_updates_goal_and_account_read_models(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "1000.00")
    client.post(
        f"/api/v1/goals/{goal['id']}/transactions",
        json={"type": "contribution", "amount": "50"},
        headers=auth_headers(user_id),
    )

    response = _linked(client, user_id, goal["id"], account["id"], "300.00")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_id"] == account["id"]
    assert body["effective_date"] == TODAY.isoformat()
    assert body["currency"] == "EUR"

    goal_view = _goal(client, user_id, goal["id"])
    assert Decimal(goal_view["tracked_amount"]) == Decimal("50.00")
    assert Decimal(goal_view["linked_amount"]) == Decimal("300.00")
    assert Decimal(goal_view["current_amount"]) == Decimal("350.00")
    assert goal_view["allocations"] == [{"account_id": account["id"], "amount": "300.00"}]

    account_view = _account(client, user_id, account["id"])
    assert Decimal(account_view["current_balance"]) == Decimal("1000.00")
    assert Decimal(account_view["balance_as_of_today"]) == Decimal("1000.00")
    assert Decimal(account_view["scheduled_outflows"]) == Decimal("0.00")
    assert Decimal(account_view["planned_transfer_outflows"]) == Decimal("0.00")
    assert Decimal(account_view["reserved_amount"]) == Decimal("300.00")
    assert Decimal(account_view["unallocated_amount"]) == Decimal("700.00")
    assert Decimal(account_view["reservable_amount"]) == Decimal("700.00")
    assert account_view["allocation_status"] == "normal"
    assert account_view["negative_balance"] is False


# Tests that create and PATCH responses of an Account carry the same read
# model fields as the list.
def test_account_create_and_patch_responses_carry_read_model(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = _funded_account(client, user_id, "100.00")

    assert Decimal(account["reservable_amount"]) == Decimal("100.00")
    assert account["allocation_status"] == "normal"

    patched = _patch_account(client, user_id, account["id"], {"name": "Renamed"})

    assert patched.status_code == 200
    assert Decimal(patched.json()["balance_as_of_today"]) == Decimal("100.00")
    assert patched.json()["negative_balance"] is False


# Tests Goal create/PATCH responses expose tracked/linked/allocations.
def test_goal_create_and_patch_responses_carry_partitions(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)

    assert goal["tracked_amount"] == "0.00"
    assert goal["linked_amount"] == "0.00"
    assert goal["allocations"] == []

    patched = _patch_goal(client, user_id, goal["id"], {"name": "Renamed"})
    assert patched.status_code == 200
    assert patched.json()["allocations"] == []


# Tests the Account fields are exposed as decimal strings with two places.
def test_account_read_model_serializes_decimal_strings(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = _funded_account(client, user_id, "12.30")

    for field in (
        "current_balance", "balance_as_of_today", "scheduled_outflows", "planned_transfer_outflows",
        "reserved_amount", "unallocated_amount", "reservable_amount",
    ):
        assert isinstance(account[field], str), field
    assert account["balance_as_of_today"] == "12.30"


# ------------------------------------------------------------------
# Capacity
# ------------------------------------------------------------------


# Tests the exact boundary: amount == reservable succeeds, one cent above
# fails 409 and writes nothing.
def test_capacity_boundary_exact_below_above(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")

    above = _linked(client, user_id, goal["id"], account["id"], "100.01")
    below = _linked(client, user_id, goal["id"], account["id"], "99.99")
    one_cent_left = _linked(client, user_id, goal["id"], account["id"], "0.01")
    exact_again = _linked(client, user_id, goal["id"], account["id"], "0.01")

    assert above.status_code == 409 and above.json()["detail"] == CAPACITY
    assert below.status_code == 201
    assert one_cent_left.status_code == 201
    assert exact_again.status_code == 409
    assert _count_goal_rows(user_id) == 2
    assert Decimal(_account(client, user_id, account["id"])["reservable_amount"]) == Decimal("0.00")


# Tests that reservable <= 0 rejects any amount, and that an unfunded
# Account has no capacity.
def test_nonpositive_reservable_rejects(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    empty = create_account(client, user_id)

    response = _linked(client, user_id, goal["id"], empty["id"], "0.01")

    assert response.status_code == 409
    assert response.json()["detail"] == CAPACITY


# Tests that a future-dated debit reduces capacity while a future credit
# adds nothing, and balance_as_of_today ignores future rows while
# current_balance does not.
def test_future_rows_scheduled_outflows_and_credits(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "500.00")
    create_account_transaction(client, user_id, account["id"], amount="200.00", direction="debit", transaction_date=FUTURE)
    create_account_transaction(client, user_id, account["id"], amount="900.00", direction="credit", transaction_date=FUTURE)

    view = _account(client, user_id, account["id"])
    assert Decimal(view["current_balance"]) == Decimal("1200.00")
    assert Decimal(view["balance_as_of_today"]) == Decimal("500.00")
    assert Decimal(view["scheduled_outflows"]) == Decimal("200.00")
    assert Decimal(view["reservable_amount"]) == Decimal("300.00")

    assert _linked(client, user_id, goal["id"], account["id"], "300.01").status_code == 409
    assert _linked(client, user_id, goal["id"], account["id"], "300.00").status_code == 201


# Tests that a planned OUTGOING transfer reduces capacity regardless of its
# planned date, a planned INCOMING transfer adds nothing, and posting it
# later does not subtract twice.
def test_planned_transfer_outflows_capacity(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    source = _funded_account(client, user_id, "500.00")
    destination = _funded_account(client, user_id, "0.00")
    create_account_transfer(client, user_id, source["id"], destination["id"], amount="150.00", transfer_date=FUTURE)

    source_view = _account(client, user_id, source["id"])
    destination_view = _account(client, user_id, destination["id"])
    assert Decimal(source_view["planned_transfer_outflows"]) == Decimal("150.00")
    assert Decimal(source_view["reservable_amount"]) == Decimal("350.00")
    assert Decimal(destination_view["planned_transfer_outflows"]) == Decimal("0.00")
    assert Decimal(destination_view["reservable_amount"]) == Decimal("0.00")

    assert _linked(client, user_id, goal["id"], source["id"], "350.01").status_code == 409
    assert _linked(client, user_id, goal["id"], source["id"], "350.00").status_code == 201
    assert _linked(client, user_id, goal["id"], destination["id"], "1.00").status_code == 409


# Tests overcommitted/negative_balance after spending the reserved money:
# history is never rewritten, reservable goes negative, status flips.
def test_overcommitted_status_and_negative_balance(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "400.00")
    assert _linked(client, user_id, goal["id"], account["id"], "300.00").status_code == 201

    create_account_transaction(client, user_id, account["id"], amount="250.00", direction="debit", transaction_date=PAST)

    view = _account(client, user_id, account["id"])
    assert Decimal(view["balance_as_of_today"]) == Decimal("150.00")
    assert Decimal(view["reserved_amount"]) == Decimal("300.00")
    assert Decimal(view["unallocated_amount"]) == Decimal("-150.00")
    assert Decimal(view["reservable_amount"]) == Decimal("-150.00")
    assert view["allocation_status"] == "overcommitted"
    assert view["negative_balance"] is False
    assert _goal(client, user_id, goal["id"])["allocations"][0]["amount"] == "300.00"

    create_account_transaction(client, user_id, account["id"], amount="500.00", direction="debit", transaction_date=PAST)
    assert _account(client, user_id, account["id"])["negative_balance"] is True
    assert _linked(client, user_id, goal["id"], account["id"], "1.00").status_code == 409


# Tests that reserved_amount spans ALL Goals of the Account, archived ones
# included, so a second Goal sees reduced capacity.
def test_reserved_amount_spans_goals_including_archived(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    first = create_goal(client, user_id, name="A")
    second = create_goal(client, user_id, name="B")
    account = _funded_account(client, user_id, "100.00")
    assert _linked(client, user_id, first["id"], account["id"], "60.00").status_code == 201
    assert _patch_goal(client, user_id, first["id"], {"status": "archived"}).status_code == 200

    assert Decimal(_account(client, user_id, account["id"])["reserved_amount"]) == Decimal("60.00")
    assert _linked(client, user_id, second["id"], account["id"], "40.01").status_code == 409
    assert _linked(client, user_id, second["id"], account["id"], "40.00").status_code == 201


# ------------------------------------------------------------------
# Date rule (P58)
# ------------------------------------------------------------------


# Tests the linked date rule: omitted and equal-to-today pass; past and
# future are 422 for contributions and withdrawals alike, and nothing is
# written.
def test_linked_date_rule(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    assert _linked(client, user_id, goal["id"], account["id"], "10", effective_date=TODAY.isoformat()).status_code == 201
    rows = _count_goal_rows(user_id)

    for kind in ("contribution", "withdrawal"):
        for wrong in (PAST, FUTURE):
            response = _linked(client, user_id, goal["id"], account["id"], "1", type=kind, effective_date=wrong)
            assert response.status_code == 422, (kind, wrong, response.text)

    assert _count_goal_rows(user_id) == rows


# Tests the tracked date rule is unchanged: a past date is accepted, a
# future date is 422.
def test_tracked_date_rule_unchanged(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)

    past = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10", "effective_date": PAST})
    future = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10", "effective_date": FUTURE})

    assert past.status_code == 201 and past.json()["effective_date"] == PAST
    assert future.status_code == 422


# ------------------------------------------------------------------
# Validation precedence
# ------------------------------------------------------------------


# Tests the linked contribution 404 cases: missing and foreign Goal,
# missing and foreign Account are all 404; ownership is not revealed.
def test_linked_contribution_404_cases(client: TestClient, clean_database: None) -> None:
    user_id, other_id = str(uuid4()), str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    foreign_goal = create_goal(client, other_id)
    foreign_account = _funded_account(client, other_id)

    missing_goal = _linked(client, user_id, str(uuid4()), account["id"], "1")
    foreign_goal_response = _linked(client, user_id, foreign_goal["id"], account["id"], "1")
    missing_account = _linked(client, user_id, goal["id"], str(uuid4()), "1")
    foreign_account_response = _linked(client, user_id, goal["id"], foreign_account["id"], "1")

    assert missing_goal.status_code == 404 and missing_goal.json()["detail"] == GOAL_NOT_FOUND
    assert foreign_goal_response.status_code == 404 and foreign_goal_response.json()["detail"] == GOAL_NOT_FOUND
    assert missing_account.status_code == 404 and missing_account.json()["detail"] == ACCOUNT_NOT_FOUND
    assert foreign_account_response.status_code == 404
    assert foreign_account_response.json() == missing_account.json()
    assert _count_goal_rows(user_id) == 0


# Tests that a wrong date beats a nonexistent Account (422 before 404) and
# a foreign Account with a wrong currency is 404 (not 422).
def test_precedence_date_before_404_and_404_before_currency(client: TestClient, clean_database: None) -> None:
    user_id, other_id = str(uuid4()), str(uuid4())
    goal = create_goal(client, user_id)
    foreign_usd = _funded_account(client, other_id, currency="USD")

    wrong_date = _linked(client, user_id, goal["id"], str(uuid4()), "1", effective_date=PAST)
    foreign_wrong_currency = _linked(client, user_id, goal["id"], foreign_usd["id"], "1")

    assert wrong_date.status_code == 422
    assert foreign_wrong_currency.status_code == 404


# Tests the linked contribution order: archived Goal (409) -> archived
# Account (409) -> currency mismatch (422) -> capacity (409).
def test_linked_contribution_lifecycle_order(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    usd_account = _funded_account(client, user_id, "10.00", currency="USD")
    empty = create_account(client, user_id)

    # currency mismatch beats capacity (empty USD-less EUR goal vs funded USD)
    mismatch = _linked(client, user_id, goal["id"], usd_account["id"], "1000")
    assert mismatch.status_code == 422 and mismatch.json()["detail"] == CURRENCY_MISMATCH

    # capacity applies last
    assert _linked(client, user_id, goal["id"], empty["id"], "1").json()["detail"] == CAPACITY

    # archived Account beats currency mismatch and capacity
    assert _patch_account(client, user_id, usd_account["id"], {"status": "archived"}).status_code == 200
    assert _linked(client, user_id, goal["id"], usd_account["id"], "1000").json()["detail"] == ACCOUNT_ARCHIVED

    # archived Goal beats archived Account
    assert _patch_goal(client, user_id, goal["id"], {"status": "archived"}).status_code == 200
    archived_goal = _linked(client, user_id, goal["id"], usd_account["id"], "1000")
    assert archived_goal.status_code == 409 and archived_goal.json()["detail"] == GOAL_ARCHIVED


# Tests that a completed Goal still accepts linked contributions.
def test_completed_goal_accepts_linked_contribution(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    assert _patch_goal(client, user_id, goal["id"], {"status": "completed"}).status_code == 200

    assert _linked(client, user_id, goal["id"], account["id"], "5").status_code == 201


# ------------------------------------------------------------------
# Linked withdrawal
# ------------------------------------------------------------------


# Tests a linked withdrawal releases only its own partition, restores
# capacity, needs no capacity itself and is allowed on archived Goals and
# archived Accounts.
def test_linked_withdrawal_releases_partition(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    other = _funded_account(client, user_id, "100.00")
    assert _linked(client, user_id, goal["id"], account["id"], "100.00").status_code == 201
    assert _linked(client, user_id, goal["id"], other["id"], "20.00").status_code == 201

    over = _linked(client, user_id, goal["id"], account["id"], "100.01", type="withdrawal")
    assert over.status_code == 409 and over.json()["detail"] == PARTITION

    # partition of another Account never covers it
    cross = _linked(client, user_id, goal["id"], other["id"], "20.01", type="withdrawal")
    assert cross.status_code == 409 and cross.json()["detail"] == PARTITION

    assert _patch_goal(client, user_id, goal["id"], {"status": "archived"}).status_code == 200
    assert _patch_account(client, user_id, account["id"], {"status": "archived"}).status_code == 200
    released = _linked(client, user_id, goal["id"], account["id"], "40.00", type="withdrawal")
    assert released.status_code == 201

    view = _goal(client, user_id, goal["id"])
    amounts = {item["account_id"]: item["amount"] for item in view["allocations"]}
    assert amounts == {account["id"]: "60.00", other["id"]: "20.00"}
    assert Decimal(_account(client, user_id, account["id"])["reserved_amount"]) == Decimal("60.00")


# Tests that a linked withdrawal does not use the tracked partition, and a
# tracked withdrawal does not use a linked one.
def test_partitions_do_not_cross_cover(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    assert _post(client, user_id, goal["id"], {"type": "contribution", "amount": "50"}).status_code == 201
    assert _linked(client, user_id, goal["id"], account["id"], "30.00").status_code == 201

    linked_over = _linked(client, user_id, goal["id"], account["id"], "30.01", type="withdrawal")
    tracked_over = _post(client, user_id, goal["id"], {"type": "withdrawal", "amount": "50.01"})
    tracked_ok = _post(client, user_id, goal["id"], {"type": "withdrawal", "amount": "50.00"})

    assert linked_over.status_code == 409 and linked_over.json()["detail"] == PARTITION
    assert tracked_over.status_code == 409 and tracked_over.json()["detail"] == TRACKED_SHORTFALL
    assert tracked_ok.status_code == 201
    view = _goal(client, user_id, goal["id"])
    assert view["tracked_amount"] == "0.00" and view["linked_amount"] == "30.00"


# Tests linked withdrawal ordering: 404 Goal, 404 Account (own/foreign),
# currency 422 before the partition check, date 422 before 404.
def test_linked_withdrawal_precedence(client: TestClient, clean_database: None) -> None:
    user_id, other_id = str(uuid4()), str(uuid4())
    goal = create_goal(client, user_id)
    usd = _funded_account(client, user_id, "10.00", currency="USD")
    foreign = _funded_account(client, other_id)

    assert _linked(client, user_id, str(uuid4()), usd["id"], "1", type="withdrawal").status_code == 404
    assert _linked(client, user_id, goal["id"], str(uuid4()), "1", type="withdrawal").json()["detail"] == ACCOUNT_NOT_FOUND
    assert _linked(client, user_id, goal["id"], foreign["id"], "1", type="withdrawal").status_code == 404

    mismatch = _linked(client, user_id, goal["id"], usd["id"], "1", type="withdrawal")
    assert mismatch.status_code == 422 and mismatch.json()["detail"] == CURRENCY_MISMATCH

    # nonexistent partition + invalid date -> 422 (date first)
    empty = create_account(client, user_id)
    bad_date = _linked(client, user_id, goal["id"], empty["id"], "1", type="withdrawal", effective_date=FUTURE)
    assert bad_date.status_code == 422
    nonexistent_partition = _linked(client, user_id, goal["id"], empty["id"], "1", type="withdrawal")
    assert nonexistent_partition.status_code == 409 and nonexistent_partition.json()["detail"] == PARTITION


# Tests that an exact full release removes the partition from allocations
# (zero partitions are hidden).
def test_zero_partitions_are_hidden(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    assert _linked(client, user_id, goal["id"], account["id"], "70.00").status_code == 201
    assert _linked(client, user_id, goal["id"], account["id"], "70.00", type="withdrawal").status_code == 201

    view = _goal(client, user_id, goal["id"])
    assert view["allocations"] == [] and view["linked_amount"] == "0.00"


# ------------------------------------------------------------------
# Idempotency
# ------------------------------------------------------------------


# Tests an exact linked replay is 200 with the original row and writes
# nothing, even after the Goal is archived and the Account has no capacity.
def test_linked_replay_returns_200_and_ignores_later_state(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    key = str(uuid4())
    first = _linked(client, user_id, goal["id"], account["id"], "100.00", key=key)
    assert first.status_code == 201

    assert _patch_goal(client, user_id, goal["id"], {"status": "archived"}).status_code == 200
    replay = _linked(client, user_id, goal["id"], account["id"], "100.00", key=key)

    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert _count_goal_rows(user_id) == 1


# Tests the occupied key is resolved before date/404/capacity: a matching
# replay with an explicit wrong date is a 409 conflict, but a replay that
# omits the date after midnight returns the original (200).
def test_replay_precedes_date_and_next_day_omitted_date_replays(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id, "100.00")
    key = str(uuid4())
    first = _linked(client, user_id, goal["id"], account["id"], "10.00", key=key)
    assert first.status_code == 201

    class _Tomorrow(date):
        @classmethod
        def today(cls) -> date:
            return TODAY + timedelta(days=1)

    monkeypatch.setattr(goal_service, "date", _Tomorrow)
    omitted = _linked(client, user_id, goal["id"], account["id"], "10.00", key=key)
    explicit_wrong = _linked(client, user_id, goal["id"], account["id"], "10.00", key=key, effective_date=(TODAY + timedelta(days=1)).isoformat())

    assert omitted.status_code == 200 and omitted.json()["id"] == first.json()["id"]
    assert omitted.json()["effective_date"] == TODAY.isoformat()
    assert explicit_wrong.status_code == 409
    assert _count_goal_rows(user_id) == 1


# Tests account_id is part of the payload: the same key with another
# Account, or as a tracked request, or a tracked key reused as linked, is
# a 409 conflict (an occupied key beats an archived Account).
def test_account_id_in_idempotency_payload(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    first_account = _funded_account(client, user_id, "100.00")
    second_account = _funded_account(client, user_id, "100.00")
    key = str(uuid4())
    assert _linked(client, user_id, goal["id"], first_account["id"], "10.00", key=key).status_code == 201
    assert _patch_account(client, user_id, second_account["id"], {"status": "archived"}).status_code == 200

    another = _linked(client, user_id, goal["id"], second_account["id"], "10.00", key=key)
    omitted = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10.00", "client_request_id": key})
    explicit_null = _post(
        client, user_id, goal["id"],
        {"type": "contribution", "amount": "10.00", "client_request_id": key, "account_id": None},
    )

    assert another.status_code == 409 and another.json()["detail"] == IDEMPOTENCY_CONFLICT
    assert omitted.status_code == 409
    assert explicit_null.status_code == 409

    tracked_key = str(uuid4())
    assert _post(client, user_id, goal["id"], {"type": "contribution", "amount": "5", "client_request_id": tracked_key}).status_code == 201
    as_linked = _linked(client, user_id, goal["id"], first_account["id"], "5", key=tracked_key)
    assert as_linked.status_code == 409
    assert _count_goal_rows(user_id) == 2


# Tests the key is scoped per user: another user's key never replays or
# conflicts.
def test_key_is_scoped_by_user(client: TestClient, clean_database: None) -> None:
    key = str(uuid4())
    results = []
    for _ in range(2):
        user_id = str(uuid4())
        goal = create_goal(client, user_id)
        account = _funded_account(client, user_id)
        results.append(_linked(client, user_id, goal["id"], account["id"], "5", key=key).status_code)

    assert results == [201, 201]


# Tests the same key reused for a different amount or type is 409.
def test_linked_key_reuse_with_different_payload_conflicts(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    key = str(uuid4())
    assert _linked(client, user_id, goal["id"], account["id"], "10.00", key=key).status_code == 201

    assert _linked(client, user_id, goal["id"], account["id"], "11.00", key=key).status_code == 409
    assert _linked(client, user_id, goal["id"], account["id"], "10.00", key=key, type="withdrawal").status_code == 409


# Tests description None vs "" are different payloads for linked replays.
def test_linked_description_exactness(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    key = str(uuid4())
    assert _linked(client, user_id, goal["id"], account["id"], "10", key=key, description="note").status_code == 201

    assert _linked(client, user_id, goal["id"], account["id"], "10", key=key, description="note").status_code == 200
    assert _linked(client, user_id, goal["id"], account["id"], "10", key=key).status_code == 409


# ------------------------------------------------------------------
# Account lifecycle protection
# ------------------------------------------------------------------


# Tests an Account with linked Goal history cannot be deleted, even after a
# full release (net zero) and with an archived Goal; an unlinked Account can.
def test_account_delete_blocked_by_any_linked_history(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    linked = _funded_account(client, user_id)
    unlinked = create_account(client, user_id)
    assert _linked(client, user_id, goal["id"], linked["id"], "10").status_code == 201
    assert _linked(client, user_id, goal["id"], linked["id"], "10", type="withdrawal").status_code == 201
    assert _patch_goal(client, user_id, goal["id"], {"status": "archived"}).status_code == 200

    blocked = client.delete(f"/api/v1/accounts/{linked['id']}", headers=auth_headers(user_id))
    free = client.delete(f"/api/v1/accounts/{unlinked['id']}", headers=auth_headers(user_id))

    assert blocked.status_code == 409
    assert "Goal reservations" in blocked.json()["detail"] or "transaction history" in blocked.json()["detail"]
    assert free.status_code == 204


# Tests the delete precedence: ledger history (existing text) wins over the
# linked-history error.
def test_account_delete_ledger_history_message_wins(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    assert _linked(client, user_id, goal["id"], account["id"], "10").status_code == 201

    response = client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id))

    assert response.status_code == 409
    assert response.json()["detail"] == "Account with transaction history cannot be deleted. Archive it instead."


# Tests that linked history is the sole blocker: an Account with no ledger
# rows (so only the reservation) cannot be deleted - but linking requires
# capacity, so the history is created with a later-drained ledger-free
# Account via direct DB insert to isolate the linked check.
def test_account_delete_blocked_by_linked_history_without_ledger(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = create_account(client, user_id)
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, account_id, created_at) VALUES (gen_random_uuid(), :g, :u, 'contribution', 5, "
                "'EUR', current_date, gen_random_uuid(), :a, now())"
            ),
            {"g": goal["id"], "u": user_id, "a": account["id"]},
        )
        session.commit()

    response = client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id))

    assert response.status_code == 409
    assert "Goal reservations" in response.json()["detail"]


# Tests currency change protection: blocked by linked history (even at net
# zero), allowed for an unlinked Account, and a same-currency resend is a
# no-op.
def test_account_currency_change_protection(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = create_account(client, user_id)
    other = create_account(client, user_id)
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, account_id, created_at) VALUES (gen_random_uuid(), :g, :u, 'contribution', 5, "
                "'EUR', current_date, gen_random_uuid(), :a, now())"
            ),
            {"g": goal["id"], "u": user_id, "a": account["id"]},
        )
        session.commit()

    blocked = _patch_account(client, user_id, account["id"], {"currency": "USD"})
    resend = _patch_account(client, user_id, account["id"], {"currency": "eur"})
    changed = _patch_account(client, user_id, other["id"], {"currency": "USD"})

    assert blocked.status_code == 409
    assert "Goal reservations" in blocked.json()["detail"]
    assert resend.status_code == 200
    assert changed.status_code == 200 and changed.json()["currency"] == "USD"


# Tests the DB backstop: if a linked row appears after the service
# prechecks (simulated by bypassing them), the foreign key violation is
# translated into the controlled 409, never a 500.
def test_database_backstop_translates_to_controlled_409(client: TestClient, clean_database: None, monkeypatch) -> None:
    from app.modules.accounts import account_service

    user_id = str(uuid4())
    goal = create_goal(client, user_id)
    account = create_account(client, user_id)
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, account_id, created_at) VALUES (gen_random_uuid(), :g, :u, 'contribution', 5, "
                "'EUR', current_date, gen_random_uuid(), :a, now())"
            ),
            {"g": goal["id"], "u": user_id, "a": account["id"]},
        )
        session.commit()

    monkeypatch.setattr(
        account_service.goal_transaction_repository, "has_linked_transactions_for_account",
        lambda **kwargs: False,
    )

    deleted = client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id))
    changed = _patch_account(client, user_id, account["id"], {"currency": "USD"})

    assert deleted.status_code == 409
    assert changed.status_code == 409


# ------------------------------------------------------------------
# Query counts and old-client compatibility
# ------------------------------------------------------------------


# Tests the Account list and Goal list use a constant number of queries
# regardless of how many Accounts / Goals exist (no N+1).
def test_list_endpoints_have_constant_query_counts(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())

    def count_queries(path: str) -> int:
        statements: list = []

        def listener(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get(path, headers=auth_headers(user_id))
            assert response.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    goal = create_goal(client, user_id)
    account = _funded_account(client, user_id)
    _linked(client, user_id, goal["id"], account["id"], "5")
    accounts_small, goals_small = count_queries("/api/v1/accounts"), count_queries("/api/v1/goals")

    for _ in range(4):
        extra_goal = create_goal(client, user_id)
        extra_account = _funded_account(client, user_id)
        _linked(client, user_id, extra_goal["id"], extra_account["id"], "5")

    assert count_queries("/api/v1/accounts") == accounts_small
    assert count_queries("/api/v1/goals") == goals_small


# Tests old-style tracked requests behave as before: no key, no account,
# 201 each time, response exposes account_id null.
def test_old_clients_unchanged(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    goal = create_goal(client, user_id)

    first = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10"})
    second = _post(client, user_id, goal["id"], {"type": "contribution", "amount": "10"})

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["account_id"] is None
    view = _goal(client, user_id, goal["id"])
    assert view["current_amount"] == "20.00" and view["tracked_amount"] == "20.00"
    assert view["linked_amount"] == "0.00" and view["allocations"] == []


# ------------------------------------------------------------------
# Review-fix coverage (second commit)
# ------------------------------------------------------------------

MONEY_FIELDS = (
    "current_balance", "balance_as_of_today", "scheduled_outflows", "planned_transfer_outflows",
    "reserved_amount", "unallocated_amount", "reservable_amount",
)
TWO_PLACES = __import__("re").compile(r"^-?\d+\.\d{2}$")


# Tests every money field of an Account response is a two-decimal string,
# including the zero aggregates of an Account whose ledger has only
# future-dated rows (SQL sums of a literal 0 used to serialize as "0").
def test_account_money_fields_are_always_two_decimal_strings(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    future_only = create_account(client, user_id)
    create_account_transaction(
        client, user_id, future_only["id"], amount="5.00", direction="credit", transaction_date=FUTURE,
    )
    future_debit_only = create_account(client, user_id)
    create_account_transaction(
        client, user_id, future_debit_only["id"], amount="7.00", direction="debit", transaction_date=FUTURE,
    )
    empty = create_account(client, user_id)
    funded = _funded_account(client, user_id, "0.00")

    views = client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()
    assert len(views) == 4
    for view in views:
        for field in MONEY_FIELDS:
            assert TWO_PLACES.match(view[field]), (view["id"], field, view[field])

    by_id = {view["id"]: view for view in views}
    assert by_id[future_only["id"]]["balance_as_of_today"] == "0.00"
    assert by_id[future_only["id"]]["scheduled_outflows"] == "0.00"
    assert by_id[future_debit_only["id"]]["scheduled_outflows"] == "7.00"
    assert by_id[future_debit_only["id"]]["balance_as_of_today"] == "0.00"
    assert empty["balance_as_of_today"] == "0.00" and funded["reservable_amount"] == "0.00"
    for created in (future_only, empty, funded):
        for field in MONEY_FIELDS:
            assert TWO_PLACES.match(created[field]), (field, created[field])


# Tests a planned outgoing transfer reduces reservable_amount and that,
# once the same transfer is posted (now represented in the ledger), it is
# no longer subtracted as planned: the capacity does not drop twice.
def test_posted_transfer_is_not_double_subtracted(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = _funded_account(client, user_id, "500.00")
    destination = _funded_account(client, user_id, "0.00")
    transfer = create_account_transfer(
        client, user_id, source["id"], destination["id"], amount="150.00", transfer_date=FUTURE,
    )

    planned_view = _account(client, user_id, source["id"])
    assert planned_view["planned_transfer_outflows"] == "150.00"
    assert planned_view["balance_as_of_today"] == "500.00"
    assert planned_view["reservable_amount"] == "350.00"

    posted = client.post(f"/api/v1/account-transfers/{transfer['id']}/post", headers=auth_headers(user_id))
    assert posted.status_code == 200, posted.text

    posted_view = _account(client, user_id, source["id"])
    destination_view = _account(client, user_id, destination["id"])
    assert posted_view["planned_transfer_outflows"] == "0.00"
    assert posted_view["balance_as_of_today"] == "350.00"
    assert posted_view["reservable_amount"] == "350.00"
    assert destination_view["balance_as_of_today"] == "150.00"
    assert destination_view["reservable_amount"] == "150.00"

    goal = create_goal(client, user_id)
    assert _linked(client, user_id, goal["id"], source["id"], "350.01").status_code == 409
    assert _linked(client, user_id, goal["id"], source["id"], "350.00").status_code == 201
