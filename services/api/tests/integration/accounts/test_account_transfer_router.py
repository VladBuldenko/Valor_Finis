from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.modules.accounts import account_transfer_service
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import AccountTransferCreate
from tests.helpers import (
    auth_headers,
    create_account,
    create_account_transaction,
    create_account_transfer,
)

# Every date below is chosen relative to the real server date so the tests
# never depend on when they run: PAST is always <= today (immediately
# posted), FUTURE is always > today (planned).
PAST = "2026-09-01"
FUTURE = (date.today() + timedelta(days=30)).isoformat()

ACCOUNT_NOT_FOUND = "Account not found."
ARCHIVED = "Archived account cannot receive new transactions."
CURRENCY_MISMATCH = "Transfer source and destination accounts must use the same currency."
IDEMPOTENCY_CONFLICT = "client_request_id has already been used for a different transfer."
PLANNED_REFERENCE = "Account is referenced by planned transfers. Delete them first."
TRANSFER_NOT_FOUND = "Account transfer not found."


def _balances(client: TestClient, user_id: str) -> dict[str, Decimal]:
    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return {account["id"]: Decimal(account["current_balance"]) for account in response.json()}


def _history(client: TestClient, user_id: str, account_id: str) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/v1/accounts/{account_id}/transactions", headers=auth_headers(user_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post_transfer(
    client: TestClient,
    user_id: str,
    source_id: str,
    destination_id: str,
    key: str,
    amount: str = "300.00",
    transfer_date: str = PAST,
    description: Optional[str] = None,
    include_description: bool = False,
):
    payload: dict[str, Any] = {
        "client_request_id": key,
        "source_account_id": source_id,
        "destination_account_id": destination_id,
        "amount": amount,
        "transfer_date": transfer_date,
    }
    if include_description or description is not None:
        payload["description"] = description
    return client.post(
        "/api/v1/account-transfers", headers=auth_headers(user_id), json=payload,
    )


def _db_counts(user_id: str) -> tuple:
    db_session = SessionLocal()
    try:
        transfers = (
            db_session.query(AccountTransferModel)
            .filter(AccountTransferModel.user_id == UUID(user_id))
            .count()
        )
        legs = (
            db_session.query(AccountTransactionModel)
            .filter(
                AccountTransactionModel.user_id == UUID(user_id),
                AccountTransactionModel.kind == "transfer",
            )
            .count()
        )
        return transfers, legs
    finally:
        db_session.close()


def _archive(client: TestClient, user_id: str, account_id: str) -> None:
    response = client.patch(
        f"/api/v1/accounts/{account_id}",
        headers=auth_headers(user_id),
        json={"status": "archived"},
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- create


# Tests that a transfer dated today or earlier is created posted (201),
# with planned_date null, effective_date = transfer_date, posted_at set, the
# server-derived currency, no transfer_date field, and balances moved by
# -amount/+amount so their sum is unchanged.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response and balances match.
def test_create_posted_transfer_returns_201_and_moves_balances(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings", opening_balance="50.00")
    before = _balances(client, user_id)

    transfer = create_account_transfer(
        client, user_id, source["id"], destination["id"],
        amount="300.00", transfer_date=PAST, description="Move to savings",
    )

    assert transfer["status"] == "posted"
    assert transfer["planned_date"] is None
    assert transfer["effective_date"] == PAST
    assert transfer["posted_at"] is not None
    assert transfer["currency"] == "EUR"
    assert transfer["amount"] == "300.00"
    assert transfer["description"] == "Move to savings"
    assert transfer["user_id"] == user_id
    assert "transfer_date" not in transfer

    after = _balances(client, user_id)
    assert after[source["id"]] - before[source["id"]] == Decimal("-300.00")
    assert after[destination["id"]] - before[destination["id"]] == Decimal("300.00")
    assert sum(after.values()) == sum(before.values())
    assert _db_counts(user_id) == (1, 2)


# Tests that a future-dated transfer is created planned (201) with
# planned_date set, effective_date/posted_at null, zero ledger rows, and
# unchanged balances and histories.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if nothing reaches the ledger.
def test_create_planned_transfer_returns_201_without_ledger_rows(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings")
    before = _balances(client, user_id)

    transfer = create_account_transfer(
        client, user_id, source["id"], destination["id"], transfer_date=FUTURE,
    )

    assert transfer["status"] == "planned"
    assert transfer["planned_date"] == FUTURE
    assert transfer["effective_date"] is None
    assert transfer["posted_at"] is None
    assert _balances(client, user_id) == before
    assert [row["kind"] for row in _history(client, user_id, source["id"])] == ["opening_balance"]
    assert _history(client, user_id, destination["id"]) == []
    assert _db_counts(user_id) == (1, 0)


# Tests that a posted transfer may overdraw the source Account.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the source balance becomes negative.
def test_create_transfer_allows_negative_source_balance(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="100.00")
    destination = create_account(client, user_id, name="Savings")

    create_account_transfer(client, user_id, source["id"], destination["id"], amount="250.00")

    assert _balances(client, user_id)[source["id"]] == Decimal("-150.00")


# Tests that a missing or another user's Account on either side is a 404
# "Account not found." raised by the service (the payload itself is valid),
# never revealing whether a foreign Account exists.
# Parameters:
# - side: which side is invalid.
# - kind: missing or foreign.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 404 and nothing is created.
@pytest.mark.parametrize("side", ["source", "destination"])
@pytest.mark.parametrize("kind", ["missing", "foreign"])
def test_create_transfer_missing_or_foreign_account_returns_404(
    side: str, kind: str, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    own = create_account(client, user_id, name="Checking")
    invalid_id = (
        str(uuid4()) if kind == "missing"
        else create_account(client, str(uuid4()), name="Other user's")["id"]
    )
    source_id, destination_id = (
        (invalid_id, own["id"]) if side == "source" else (own["id"], invalid_id)
    )

    response = _post_transfer(client, user_id, source_id, destination_id, str(uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"] == ACCOUNT_NOT_FOUND
    assert _db_counts(user_id) == (0, 0)


# Tests that a new transfer from or to an archived Account is a 409.
# Parameters:
# - side: which side is archived.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 409 and nothing is created.
@pytest.mark.parametrize("side", ["source", "destination"])
def test_create_transfer_with_archived_account_returns_409(
    side: str, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    _archive(client, user_id, source["id"] if side == "source" else destination["id"])

    response = _post_transfer(client, user_id, source["id"], destination["id"], str(uuid4()))

    assert response.status_code == 409
    assert response.json()["detail"] == ARCHIVED
    assert _db_counts(user_id) == (0, 0)


# Tests that Accounts in different currencies cannot be transferred
# between (422), for both posted and planned dates.
# Parameters:
# - transfer_date: posted or planned date.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422 with the mismatch detail.
@pytest.mark.parametrize("transfer_date", [PAST, FUTURE])
def test_create_transfer_currency_mismatch_returns_422(
    transfer_date: str, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    eur = create_account(client, user_id, name="EUR", currency="EUR")
    usd = create_account(client, user_id, name="USD", currency="USD")

    response = _post_transfer(
        client, user_id, eur["id"], usd["id"], str(uuid4()), transfer_date=transfer_date,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == CURRENCY_MISMATCH
    assert _db_counts(user_id) == (0, 0)


# Tests that a transfer from an Account to itself is rejected with 422 by
# request validation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_transfer_same_account_returns_422(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)

    response = _post_transfer(client, user_id, account["id"], account["id"], str(uuid4()))

    assert response.status_code == 422
    assert _db_counts(user_id) == (0, 0)


# Tests that server-owned fields in the request body are rejected (422)
# rather than silently honored.
# Parameters:
# - field_name: the server-owned field under test.
# - value: a plausible client-supplied value.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
@pytest.mark.parametrize(
    ("field_name", "value"),
    [("currency", "EUR"), ("status", "posted"), ("user_id", str(uuid4())), ("planned_date", PAST)],
)
def test_create_transfer_rejects_server_owned_fields(
    field_name: str, value: str, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")

    response = client.post(
        "/api/v1/account-transfers",
        headers=auth_headers(user_id),
        json={
            "client_request_id": str(uuid4()),
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": "10.00",
            "transfer_date": PAST,
            field_name: value,
        },
    )

    assert response.status_code == 422
    assert _db_counts(user_id) == (0, 0)


# ----------------------------------------------------------- idempotency


# Tests that an exact replay of a planned create returns 200 with the same
# transfer and creates nothing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if there is still exactly one transfer.
def test_exact_replay_of_planned_create_returns_200(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())

    first = _post_transfer(client, user_id, source["id"], destination["id"], key, transfer_date=FUTURE)
    replay = _post_transfer(client, user_id, source["id"], destination["id"], key, transfer_date=FUTURE)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert _db_counts(user_id) == (1, 0)


# Tests that an exact replay of a posted create returns 200 without a
# second pair of projections and without double-counting balances.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if balances moved exactly once.
def test_exact_replay_of_posted_create_returns_200_without_double_counting(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())

    first = _post_transfer(client, user_id, source["id"], destination["id"], key)
    replay = _post_transfer(client, user_id, source["id"], destination["id"], key)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert _db_counts(user_id) == (1, 2)
    balances = _balances(client, user_id)
    assert balances[source["id"]] == Decimal("700.00")
    assert balances[destination["id"]] == Decimal("300.00")


# Tests that Decimal-equivalent amounts ("300" vs "300.00") are the same
# payload for replay purposes.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the replay is 200.
def test_replay_with_decimal_equivalent_amount_returns_200(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())

    assert _post_transfer(client, user_id, source["id"], destination["id"], key, amount="300.00").status_code == 201
    assert _post_transfer(client, user_id, source["id"], destination["id"], key, amount="300").status_code == 200


# Tests that reusing a client_request_id with any different payload field
# is a 409 idempotency conflict and creates nothing - including None versus
# "" for description (no normalization).
# Parameters:
# - change: which field differs from the original request.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 409 and one transfer remains.
@pytest.mark.parametrize(
    "change",
    ["amount", "source", "destination", "transfer_date", "description", "empty_description"],
)
def test_same_key_different_payload_returns_409(
    change: str, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    other = create_account(client, user_id, name="Cash")
    key = str(uuid4())

    first = _post_transfer(client, user_id, source["id"], destination["id"], key)
    assert first.status_code == 201

    arguments: dict[str, Any] = {
        "source_id": source["id"], "destination_id": destination["id"],
    }
    if change == "amount":
        arguments["amount"] = "300.01"
    elif change == "source":
        arguments["source_id"] = other["id"]
    elif change == "destination":
        arguments["destination_id"] = other["id"]
    elif change == "transfer_date":
        arguments["transfer_date"] = "2026-09-02"
    elif change == "description":
        arguments["description"] = "different"
    else:
        arguments["description"] = ""
        arguments["include_description"] = True

    response = _post_transfer(client, user_id, key=key, **arguments)

    assert response.status_code == 409
    assert response.json()["detail"] == IDEMPOTENCY_CONFLICT
    assert _db_counts(user_id) == (1, 2)


# Tests replay precedence: after an Account is archived, an exact replay
# of the original create still returns 200 with the existing transfer,
# while the same key with a different payload is an idempotency 409 - not
# the archived-Account 409 - because no Account validation reruns for an
# existing logical transfer.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both responses match.
def test_replay_after_account_archived(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())
    first = _post_transfer(client, user_id, source["id"], destination["id"], key, transfer_date=FUTURE)
    _archive(client, user_id, source["id"])

    replay = _post_transfer(client, user_id, source["id"], destination["id"], key, transfer_date=FUTURE)
    conflict = _post_transfer(
        client, user_id, source["id"], destination["id"], key,
        transfer_date=FUTURE, amount="1.00",
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["status"] == "planned"
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == IDEMPOTENCY_CONFLICT


# ------------------------------------------------------------------ list


# Tests that the list contains the user's planned and posted transfers
# newest first by COALESCE(effective_date, planned_date), and never another
# user's transfer.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if order and scope are exact.
def test_list_returns_own_transfers_in_order(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    other_source = create_account(client, other_user_id, name="Checking")
    other_destination = create_account(client, other_user_id, name="Savings")

    posted_early = create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date="2026-09-05")
    planned = create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date=FUTURE)
    posted_late = create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date="2026-09-15")
    create_account_transfer(client, other_user_id, other_source["id"], other_destination["id"])

    response = client.get("/api/v1/account-transfers", headers=auth_headers(user_id))

    assert response.status_code == 200
    assert [transfer["id"] for transfer in response.json()] == [
        planned["id"], posted_late["id"], posted_early["id"],
    ]
    assert {transfer["status"] for transfer in response.json()} == {"planned", "posted"}


# Tests that a planned transfer whose planned_date has already passed is
# listed exactly as stored - still planned, with no ledger rows - and that
# listing changes nothing (no automatic posting).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the overdue plan stays planned.
def test_overdue_planned_transfer_stays_planned_in_list(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")

    # Created as planned relative to a past "today", so its planned_date is
    # now overdue.
    db_session = SessionLocal()
    try:
        account_transfer_service.create_account_transfer(
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
        )
    finally:
        db_session.close()

    for _ in range(2):
        [listed] = client.get("/api/v1/account-transfers", headers=auth_headers(user_id)).json()
        assert listed["status"] == "planned"
        assert listed["planned_date"] == "2026-09-01"
        assert listed["effective_date"] is None

    assert _db_counts(user_id) == (1, 0)


# ---------------------------------------------------------------- delete


# Tests that deleting a planned transfer returns 204, removes it, and
# leaves balances untouched; a second delete is 404.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the transfer is gone and balances unchanged.
def test_delete_planned_transfer(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="500.00")
    destination = create_account(client, user_id, name="Savings")
    transfer = create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date=FUTURE)
    before = _balances(client, user_id)

    response = client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=auth_headers(user_id))
    again = client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=auth_headers(user_id))

    assert response.status_code == 204
    assert again.status_code == 404
    assert again.json()["detail"] == TRANSFER_NOT_FOUND
    assert _balances(client, user_id) == before
    assert _db_counts(user_id) == (0, 0)


# Tests that deleting a posted transfer returns 204, removes both ledger
# projections by cascade, and restores both balances - even when one
# Account has been archived since.
# Parameters:
# - archive_first: whether the source Account is archived before deleting.
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the balances revert.
@pytest.mark.parametrize("archive_first", [False, True])
def test_delete_posted_transfer_reverts_balances(
    archive_first: bool, client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking", opening_balance="500.00")
    destination = create_account(client, user_id, name="Savings")
    before = _balances(client, user_id)
    transfer = create_account_transfer(client, user_id, source["id"], destination["id"])
    if archive_first:
        _archive(client, user_id, source["id"])

    response = client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=auth_headers(user_id))

    assert response.status_code == 204
    assert _balances(client, user_id) == before
    assert _db_counts(user_id) == (0, 0)
    assert [row["kind"] for row in _history(client, user_id, source["id"])] == ["opening_balance"]


# Tests that deleting a missing or another user's transfer is a 404 and
# changes nothing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both deletes are 404 and the transfer survives.
def test_delete_missing_or_foreign_transfer_returns_404(
    client: TestClient, clean_database: None,
) -> None:
    owner_id = str(uuid4())
    source = create_account(client, owner_id, name="Checking")
    destination = create_account(client, owner_id, name="Savings")
    transfer = create_account_transfer(client, owner_id, source["id"], destination["id"])

    foreign = client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=auth_headers(str(uuid4())))
    missing = client.delete(f"/api/v1/account-transfers/{uuid4()}", headers=auth_headers(owner_id))

    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json() == missing.json()
    assert _db_counts(owner_id) == (1, 2)


# Tests the accepted MVP behavior: hard delete frees the client_request_id,
# so reusing it afterwards creates a new transfer (201, new id).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the recreate is a new 201.
def test_client_request_id_can_be_reused_after_hard_delete(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    key = str(uuid4())
    first = _post_transfer(client, user_id, source["id"], destination["id"], key)
    client.delete(f"/api/v1/account-transfers/{first.json()['id']}", headers=auth_headers(user_id))

    recreated = _post_transfer(client, user_id, source["id"], destination["id"], key)

    assert recreated.status_code == 201
    assert recreated.json()["id"] != first.json()["id"]
    assert _db_counts(user_id) == (1, 2)


# ------------------------------------------------------ account lifecycle


# Tests that an Account referenced by a planned transfer (and with no
# ledger history) cannot be deleted or actually change currency (409),
# while a same-value currency update and archiving stay allowed and the
# transfer stays planned; after the planned transfer is deleted, both the
# currency change and the Account delete succeed.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every step returns the expected status.
def test_planned_transfer_protects_account_delete_and_currency_change(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    headers = auth_headers(user_id)
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    transfer = create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date=FUTURE)

    for account_id in (source["id"], destination["id"]):
        delete_response = client.delete(f"/api/v1/accounts/{account_id}", headers=headers)
        assert delete_response.status_code == 409
        assert delete_response.json()["detail"] == PLANNED_REFERENCE

        currency_response = client.patch(f"/api/v1/accounts/{account_id}", headers=headers, json={"currency": "USD"})
        assert currency_response.status_code == 409
        assert currency_response.json()["detail"] == PLANNED_REFERENCE

    same_currency = client.patch(f"/api/v1/accounts/{source['id']}", headers=headers, json={"currency": "eur"})
    assert same_currency.status_code == 200
    assert same_currency.json()["currency"] == "EUR"

    _archive(client, user_id, destination["id"])
    [listed] = client.get("/api/v1/account-transfers", headers=headers).json()
    assert listed["status"] == "planned"

    assert client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=headers).status_code == 204
    assert client.patch(f"/api/v1/accounts/{source['id']}", headers=headers, json={"currency": "USD"}).status_code == 200
    assert client.delete(f"/api/v1/accounts/{destination['id']}", headers=headers).status_code == 204


# Tests that a posted transfer keeps protecting its Accounts through the
# existing ledger-history rules (not the planned-reference rule), and that
# after the transfer is deleted a history-free Account is deletable again.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the existing history errors are returned.
def test_posted_transfer_protects_accounts_through_history_rules(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    headers = auth_headers(user_id)
    source = create_account(client, user_id, name="Checking")
    destination = create_account(client, user_id, name="Savings")
    transfer = create_account_transfer(client, user_id, source["id"], destination["id"])

    delete_response = client.delete(f"/api/v1/accounts/{destination['id']}", headers=headers)
    assert delete_response.status_code == 409
    assert delete_response.json()["detail"] == (
        "Account with transaction history cannot be deleted. Archive it instead."
    )
    currency_response = client.patch(f"/api/v1/accounts/{destination['id']}", headers=headers, json={"currency": "USD"})
    assert currency_response.status_code == 409
    assert currency_response.json()["detail"] == (
        "Account currency cannot be changed after transaction history exists."
    )

    assert client.delete(f"/api/v1/account-transfers/{transfer['id']}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/accounts/{destination['id']}", headers=headers).status_code == 204


# --------------------------------------------------------------- history


# Tests the counterparty read model: each side of a posted transfer shows
# kind "transfer", the transfer id, its direction, and the OTHER Account as
# counterparty_account_id; opening_balance, adjustment, Income-linked and
# Expense-linked rows keep counterparty_account_id and transfer_id null.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every history row has the expected linkage.
def test_history_exposes_transfer_counterparty(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    headers = auth_headers(user_id)
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings")
    create_account_transaction(client, user_id, source["id"], amount="20.00", direction="debit")
    income = client.post(
        "/api/v1/income", headers=headers,
        json={"amount": "500.00", "currency": "EUR", "received_at": "2026-09-03",
              "source": "salary", "account_id": source["id"]},
    )
    assert income.status_code == 201, income.text
    expense = client.post(
        "/api/v1/expenses", headers=headers,
        json={"category_id": None, "title": "Groceries", "amount": "40.00", "currency": "EUR",
              "expense_date": "2026-09-04", "source": "manual", "account_id": source["id"]},
    )
    assert expense.status_code == 201, expense.text
    transfer = create_account_transfer(client, user_id, source["id"], destination["id"], amount="300.00")

    source_rows = _history(client, user_id, source["id"])
    [source_transfer_row] = [row for row in source_rows if row["kind"] == "transfer"]
    assert source_transfer_row["transfer_id"] == transfer["id"]
    assert source_transfer_row["direction"] == "debit"
    assert source_transfer_row["amount"] == "300.00"
    assert source_transfer_row["transaction_date"] == transfer["effective_date"]
    assert source_transfer_row["counterparty_account_id"] == destination["id"]

    other_rows = [row for row in source_rows if row["kind"] != "transfer"]
    assert {row["kind"] for row in other_rows} == {"opening_balance", "adjustment", "income", "expense"}
    for row in other_rows:
        assert row["counterparty_account_id"] is None
        assert row["transfer_id"] is None

    [destination_row] = _history(client, user_id, destination["id"])
    assert destination_row["kind"] == "transfer"
    assert destination_row["transfer_id"] == transfer["id"]
    assert destination_row["direction"] == "credit"
    assert destination_row["counterparty_account_id"] == source["id"]


# ------------------------------------------------------------- analytics


# Tests that transfers never create Income or Expense rows and leave
# expense-based analytics unchanged.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if income/expenses/monthly summary are unchanged.
def test_transfers_do_not_affect_income_expenses_or_analytics(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    headers = auth_headers(user_id)
    source = create_account(client, user_id, name="Checking", opening_balance="1000.00")
    destination = create_account(client, user_id, name="Savings")
    summary_url = "/api/v1/analytics/monthly-summary?year=2026&month=9"
    summary_before = client.get(summary_url, headers=headers).json()

    create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date="2026-09-10")
    create_account_transfer(client, user_id, source["id"], destination["id"], transfer_date=FUTURE)

    assert client.get("/api/v1/income", headers=headers).json() == []
    assert client.get("/api/v1/expenses", headers=headers).json() == []
    assert client.get(summary_url, headers=headers).json() == summary_before
