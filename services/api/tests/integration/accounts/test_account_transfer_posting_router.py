from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.modules.accounts import account_transfer_service
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_schemas import AccountTransferCreate
from tests.helpers import auth_headers, create_account, create_account_transfer

# API tests for POST /api/v1/account-transfers/{transfer_id}/post (VF-018D).
# Dates are relative to the real server date, so FUTURE is always > today
# (the transfer is planned) regardless of when the tests run.
FUTURE = (date.today() + timedelta(days=30)).isoformat()

ALREADY_POSTED = "Account transfer has already been posted."
ARCHIVED = "Archived account cannot receive new transactions."
EFFECTIVE_DATE_IN_FUTURE = "Transfer effective date cannot be in the future."
TRANSFER_NOT_FOUND = "Account transfer not found."


def _post(client: TestClient, user_id: str, transfer_id: str, body: Optional[dict] = None,
          send_body: bool = True):
    url = f"/api/v1/account-transfers/{transfer_id}/post"
    if not send_body:
        return client.post(url, headers=auth_headers(user_id))
    return client.post(url, headers=auth_headers(user_id), json=body)


def _balances(client: TestClient, user_id: str) -> dict[str, Decimal]:
    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    return {account["id"]: Decimal(account["current_balance"]) for account in response.json()}


def _history(client: TestClient, user_id: str, account_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/accounts/{account_id}/transactions", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return response.json()


def _transfer_leg_count(transfer_id: str) -> int:
    db_session = SessionLocal()
    try:
        return (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.transfer_id == UUID(transfer_id))
            .count()
        )
    finally:
        db_session.close()


def _set_status(client: TestClient, user_id: str, account_id: str, status: str) -> None:
    response = client.patch(
        f"/api/v1/accounts/{account_id}", headers=auth_headers(user_id), json={"status": status},
    )
    assert response.status_code == 200, response.text


def _planned(client: TestClient, user_id: str, source: dict, destination: dict,
             amount: str = "300.00", key: Optional[str] = None) -> dict[str, Any]:
    return create_account_transfer(
        client, user_id, source["id"], destination["id"],
        amount=amount, transfer_date=FUTURE, client_request_id=key,
    )


# Tests the three accepted body forms - no body, {}, and an explicit
# effective_date - and that the default effective_date is the server date,
# with planned_date kept and posted_at set.
# Parameters:
# - form: which body form is sent.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each form posts with the expected date.
@pytest.mark.parametrize("form", ["no_body", "empty_object", "explicit_date", "explicit_null"])
def test_post_accepts_optional_body(form: str, client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings")
    planned = _planned(client, user_id, source, destination)

    today_before = date.today().isoformat()
    if form == "no_body":
        response = _post(client, user_id, planned["id"], send_body=False)
    elif form == "empty_object":
        response = _post(client, user_id, planned["id"], body={})
    elif form == "explicit_null":
        response = _post(client, user_id, planned["id"], body={"effective_date": None})
    else:
        response = _post(client, user_id, planned["id"], body={"effective_date": "2026-09-15"})
    today_after = date.today().isoformat()

    assert response.status_code == 200, response.text
    posted = response.json()
    assert posted["id"] == planned["id"]
    assert posted["status"] == "posted"
    assert posted["planned_date"] == FUTURE
    assert posted["posted_at"] is not None
    if form == "explicit_date":
        assert posted["effective_date"] == "2026-09-15"
    else:
        assert posted["effective_date"] in {today_before, today_after}
    assert _transfer_leg_count(planned["id"]) == 2


# Tests that an unknown field in the posting body is rejected with 422.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422 and the transfer stays planned.
def test_post_rejects_unknown_body_field(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    planned = _planned(client, user_id, source, destination)

    response = _post(client, user_id, planned["id"], body={"status": "posted"})

    assert response.status_code == 422
    assert _transfer_leg_count(planned["id"]) == 0


# Tests the approved precedence: a future effective_date is 422 for an
# existing, a missing, and another user's transfer; with a valid date,
# missing and foreign transfers are the same 404.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every response matches.
def test_post_future_effective_date_precedes_lookup(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    own = _planned(client, user_id, source, destination)
    other_source = create_account(client, other_user_id, name="Checking")
    other_destination = create_account(client, other_user_id, name="Savings")
    foreign = _planned(client, other_user_id, other_source, other_destination)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    for transfer_id in (own["id"], str(uuid4()), foreign["id"]):
        response = _post(client, user_id, transfer_id, body={"effective_date": tomorrow})
        assert response.status_code == 422
        assert response.json()["detail"] == EFFECTIVE_DATE_IN_FUTURE

    missing = _post(client, user_id, str(uuid4()), body={"effective_date": "2026-09-15"})
    foreign_response = _post(client, user_id, foreign["id"], body={"effective_date": "2026-09-15"})
    assert missing.status_code == 404
    assert foreign_response.status_code == 404
    assert missing.json() == foreign_response.json() == {"detail": TRANSFER_NOT_FOUND}
    assert _transfer_leg_count(own["id"]) == 0
    assert _transfer_leg_count(foreign["id"]) == 0


# Tests that posting is at most once: the second post of a manually posted
# transfer, and any post of an immediately posted transfer, is 409 and
# adds no projections.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each transfer keeps exactly two ledger rows.
def test_post_twice_returns_409(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    planned = _planned(client, user_id, source, destination)
    immediate = create_account_transfer(client, user_id, source["id"], destination["id"])

    first = _post(client, user_id, planned["id"])
    second = _post(client, user_id, planned["id"], body={"effective_date": first.json()["effective_date"]})
    immediate_post = _post(client, user_id, immediate["id"])

    assert first.status_code == 200
    for response in (second, immediate_post):
        assert response.status_code == 409
        assert response.json()["detail"] == ALREADY_POSTED
    assert _transfer_leg_count(planned["id"]) == 2
    assert _transfer_leg_count(immediate["id"]) == 2


# Tests that posting with an archived source or destination is 409, the
# transfer stays planned with no ledger rows, deleting it stays allowed,
# and after reactivating the Account a post succeeds.
# Parameters:
# - side: which Account is archived.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every step returns the expected status.
@pytest.mark.parametrize("side", ["source", "destination"])
def test_post_with_archived_account(side: str, client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    archived_id = source["id"] if side == "source" else destination["id"]
    first = _planned(client, user_id, source, destination)
    second = _planned(client, user_id, source, destination, amount="50.00")
    _set_status(client, user_id, archived_id, "archived")

    rejected = _post(client, user_id, first["id"])

    assert rejected.status_code == 409
    assert rejected.json()["detail"] == ARCHIVED
    [listed_first] = [t for t in client.get("/api/v1/account-transfers", headers=auth_headers(user_id)).json() if t["id"] == first["id"]]
    assert listed_first["status"] == "planned"
    assert listed_first["effective_date"] is None
    assert _transfer_leg_count(first["id"]) == 0

    assert client.delete(f"/api/v1/account-transfers/{first['id']}", headers=auth_headers(user_id)).status_code == 204

    _set_status(client, user_id, archived_id, "active")
    assert _post(client, user_id, second["id"]).status_code == 200
    assert _transfer_leg_count(second["id"]) == 2


# Tests history and balances after manual posting: each side shows a
# transfer row dated effective_date with the other Account as
# counterparty, balances move by -amount/+amount with an unchanged sum, and
# the source may go negative.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if history and balances match.
def test_post_updates_history_and_balances(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="100.00")
    destination = create_account(client, user_id, name="Savings", opening_balance="20.00")
    planned = _planned(client, user_id, source, destination, amount="300.00")
    before = _balances(client, user_id)

    posted = _post(client, user_id, planned["id"], body={"effective_date": "2026-09-15"}).json()

    after = _balances(client, user_id)
    assert after[source["id"]] - before[source["id"]] == Decimal("-300.00")
    assert after[destination["id"]] - before[destination["id"]] == Decimal("300.00")
    assert after[source["id"]] == Decimal("-200.00")
    assert sum(after.values()) == sum(before.values())

    [source_row] = [row for row in _history(client, user_id, source["id"]) if row["kind"] == "transfer"]
    [destination_row] = [row for row in _history(client, user_id, destination["id"]) if row["kind"] == "transfer"]
    assert source_row["direction"] == "debit"
    assert source_row["counterparty_account_id"] == destination["id"]
    assert destination_row["direction"] == "credit"
    assert destination_row["counterparty_account_id"] == source["id"]
    for row in (source_row, destination_row):
        assert row["transfer_id"] == posted["id"]
        assert row["transaction_date"] == "2026-09-15"
        assert row["amount"] == "300.00"


# Tests that a manually posted transfer (planned_date still set) is
# hard-deleted with both projections and its balance effect reverted.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the transfer and its rows are gone.
def test_delete_after_manual_post_reverts_balances(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="500.00")
    destination = create_account(client, user_id, name="Savings")
    before = _balances(client, user_id)
    planned = _planned(client, user_id, source, destination)
    assert _post(client, user_id, planned["id"]).status_code == 200

    response = client.delete(f"/api/v1/account-transfers/{planned['id']}", headers=auth_headers(user_id))

    assert response.status_code == 204
    assert _balances(client, user_id) == before
    assert _transfer_leg_count(planned["id"]) == 0
    assert client.get("/api/v1/account-transfers", headers=auth_headers(user_id)).json() == []


# Tests the cross-slice replay rule: replaying the ORIGINAL create request
# of a planned transfer after it was manually posted returns 200 with the
# same id and its CURRENT posted state - the comparison still uses the
# original planned_date.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the replay shows the posted state.
def test_create_replay_after_manual_post_returns_current_state(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())
    planned = _planned(client, user_id, source, destination, key=key)
    posted = _post(client, user_id, planned["id"], body={"effective_date": "2026-09-15"}).json()

    replay = client.post(
        "/api/v1/account-transfers",
        headers=auth_headers(user_id),
        json={
            "client_request_id": key,
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": "300.00",
            "transfer_date": FUTURE,
        },
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["id"] == planned["id"]
    assert body["status"] == "posted"
    assert body["planned_date"] == FUTURE
    assert body["effective_date"] == "2026-09-15"
    assert body["posted_at"] == posted["posted_at"]
    assert _transfer_leg_count(planned["id"]) == 2


# Tests that create replay and posting validation are independent: after
# an Account is archived, replaying the original create is 200 (current
# planned state) while posting the same transfer is 409.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if replay is 200 and post is 409.
def test_archive_then_replay_then_post(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())
    planned = _planned(client, user_id, source, destination, key=key)
    _set_status(client, user_id, destination["id"], "archived")

    replay = client.post(
        "/api/v1/account-transfers",
        headers=auth_headers(user_id),
        json={
            "client_request_id": key,
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": "300.00",
            "transfer_date": FUTURE,
        },
    )
    post = _post(client, user_id, planned["id"])

    assert replay.status_code == 200
    assert replay.json()["status"] == "planned"
    assert post.status_code == 409
    assert post.json()["detail"] == ARCHIVED
    assert _transfer_leg_count(planned["id"]) == 0


# Tests late posting through the API: a planned transfer whose planned_date
# has already passed stays planned until posted, then posts with today's
# date while keeping the original planned_date.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the overdue plan posts with today's date.
def test_late_post_of_overdue_planned_transfer(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    db_session = SessionLocal()
    try:
        overdue = account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=AccountTransferCreate(
                client_request_id=uuid4(),
                source_account_id=UUID(source["id"]),
                destination_account_id=UUID(destination["id"]),
                amount=Decimal("300.00"),
                transfer_date=date(2026, 9, 1),
            ),
            user_id=UUID(user_id),
            as_of=date(2026, 8, 1),
        ).transfer
    finally:
        db_session.close()

    [listed] = client.get("/api/v1/account-transfers", headers=auth_headers(user_id)).json()
    assert listed["status"] == "planned"

    today_before = date.today().isoformat()
    response = _post(client, user_id, str(overdue.id))
    today_after = date.today().isoformat()

    assert response.status_code == 200
    assert response.json()["planned_date"] == "2026-09-01"
    assert response.json()["effective_date"] in {today_before, today_after}
