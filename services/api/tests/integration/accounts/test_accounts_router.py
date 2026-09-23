from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_account, create_account_transaction


# Tests that POST /accounts creates an account and returns a 0.00
# ledger-derived current_balance when no opening_balance is given.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response reflects the expected fields.
def test_create_account_endpoint_returns_created_account(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    account = create_account(client=client, user_id=user_id, name="Main Checking")

    assert account["name"] == "Main Checking"
    assert account["type"] == "checking"
    assert account["currency"] == "EUR"
    assert account["status"] == "active"
    assert account["current_balance"] == "0.00"
    assert "id" in account and "user_id" in account


# Tests that POST /accounts with a positive opening_balance returns that
# balance immediately.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if current_balance reflects the opening balance.
def test_create_account_endpoint_with_opening_balance(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    account = create_account(
        client=client, user_id=user_id, opening_balance="1000.00",
    )
    assert account["current_balance"] == "1000.00"


# Tests that POST /accounts with a negative opening_balance produces a
# negative current_balance.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if current_balance is negative.
def test_create_account_endpoint_with_negative_opening_balance(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    account = create_account(
        client=client, user_id=user_id, opening_balance="-75.00",
    )
    assert account["current_balance"] == "-75.00"


# Tests that a current_balance derived from summing multiple individually
# valid transactions can exceed a single row's own NUMERIC(12,2) range
# and still round-trip successfully through GET /accounts.
# This test exists as the regression for the remote-review finding that
# AccountResponse.current_balance previously carried max_digits=12 (the
# per-row storage limit), which would have failed FastAPI response
# validation for exactly this scenario: two individually valid
# 9,000,000,000.00 credits (each fits NUMERIC(12,2) - 12 total digits) sum
# to 18,000,000,000.00 (13 total digits), a perfectly valid ledger
# balance that must not be rejected merely because it exceeds one row's
# own range.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if GET /accounts succeeds (200) and reports the
#   full 18,000,000,000.00 sum.
def test_get_accounts_endpoint_balance_may_exceed_single_row_numeric_range(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    account = create_account(
        client=client, user_id=user_id, opening_balance="9000000000.00",
    )
    assert account["current_balance"] == "9000000000.00"

    adjustment_response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={
            "direction": "credit", "amount": "9000000000.00",
            "transaction_date": "2026-09-23",
        },
    )
    assert adjustment_response.status_code == 201

    list_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert list_response.status_code == 200
    assert list_response.json()[0]["current_balance"] == "18000000000.00"


# Tests that the API rejects a current_balance field on account creation.
# This test exists because current_balance is never client-writable.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 422.
def test_create_account_endpoint_rejects_current_balance_field(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(user_id),
        json={
            "name": "Checking", "type": "checking", "currency": "EUR",
            "current_balance": "500.00",
        },
    )
    assert response.status_code == 422


# Tests that GET /accounts returns only the authenticated user's accounts.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's account is
#   returned.
def test_get_accounts_endpoint_ownership_isolation(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_account(client=client, user_id=user_id, name="Mine")
    create_account(client=client, user_id=other_user_id, name="Theirs")

    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Mine"


# Tests that PATCH /accounts/{id} updates name and status.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both fields are updated in the response.
def test_update_account_endpoint_updates_name_and_status(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, name="Old Name")

    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={"name": "New Name", "status": "archived"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["status"] == "archived"


# Tests that PATCH /accounts/{id} rejects an empty payload.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 422.
def test_update_account_endpoint_rejects_empty_payload(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={},
    )
    assert response.status_code == 422


# Tests that another user cannot update someone else's account.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 404.
def test_update_account_endpoint_other_user_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    account = create_account(client=client, user_id=other_user_id)

    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={"name": "Hijacked"},
    )
    assert response.status_code == 404


# Tests that an actual currency change is rejected with 409 once
# transaction history exists.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 409 with the exact
#   documented error message.
def test_update_account_endpoint_currency_change_after_history_rejected(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, opening_balance="10.00")

    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={"currency": "USD"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Account currency cannot be changed after transaction history exists."
    )


# Tests that DELETE /accounts/{id} succeeds (204) when there is no
# transaction history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 204 and a subsequent
#   GET no longer includes it.
def test_delete_account_endpoint_no_history_succeeds(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    response = client.delete(
        f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id),
    )
    assert response.status_code == 204

    list_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert list_response.json() == []


# Tests that DELETE /accounts/{id} is rejected with 409 and the exact
# documented error message when transaction history exists.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 409 with the exact
#   documented error message.
def test_delete_account_endpoint_with_history_rejected(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, opening_balance="10.00")

    response = client.delete(
        f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Account with transaction history cannot be deleted. Archive it instead."
    )


# Tests that an archived account remains readable via GET /accounts along
# with its history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the archived account and its history are
#   both still returned.
def test_archived_account_remains_readable(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, opening_balance="20.00")
    client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={"status": "archived"},
    )

    list_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert list_response.json()[0]["status"] == "archived"
    assert list_response.json()[0]["current_balance"] == "20.00"

    history_response = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    )
    assert len(history_response.json()) == 1


# Tests that a new manual adjustment into an archived account is rejected
# with 409 and the exact documented error message.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 409 with the exact
#   documented error message.
def test_archived_account_rejects_new_adjustment(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)
    client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id),
        json={"status": "archived"},
    )

    response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "credit", "amount": "10.00", "transaction_date": "2026-09-23"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Archived account cannot receive new transactions."
