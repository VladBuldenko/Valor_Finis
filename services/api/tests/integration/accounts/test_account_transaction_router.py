from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_account, create_account_transaction


# Tests that POST /accounts/{id}/transactions creates a credit adjustment
# and it is reflected in the account's current_balance.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the account's balance reflects the
#   adjustment.
def test_create_account_transaction_endpoint_credit_adjustment(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    transaction = create_account_transaction(
        client=client, user_id=user_id, account_id=account["id"],
        amount="120.00", direction="credit",
    )
    assert transaction["kind"] == "adjustment"
    assert transaction["direction"] == "credit"
    assert transaction["amount"] == "120.00"

    accounts_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert accounts_response.json()[0]["current_balance"] == "120.00"


# Tests that a debit adjustment larger than the current balance succeeds
# and produces a negative account balance through the real API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the account's balance is negative.
def test_create_account_transaction_endpoint_debit_exceeding_balance_allowed(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, opening_balance="50.00")

    response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "debit", "amount": "75.00", "transaction_date": "2026-09-23"},
    )
    assert response.status_code == 201

    accounts_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert accounts_response.json()[0]["current_balance"] == "-25.00"


# Tests that the API rejects a client-supplied kind field.
# This test exists because opening_balance must never be reachable
# through this endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 422.
def test_create_account_transaction_endpoint_rejects_kind_field(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={
            "kind": "opening_balance", "direction": "credit",
            "amount": "10.00", "transaction_date": "2026-09-23",
        },
    )
    assert response.status_code == 422


# Tests that a zero or negative amount is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 422 for both cases.
def test_create_account_transaction_endpoint_rejects_non_positive_amount(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    for bad_amount in ("0.00", "-10.00"):
        response = client.post(
            f"/api/v1/accounts/{account['id']}/transactions",
            headers=auth_headers(user_id),
            json={
                "direction": "credit", "amount": bad_amount,
                "transaction_date": "2026-09-23",
            },
        )
        assert response.status_code == 422


# Tests that an invalid direction is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 422.
def test_create_account_transaction_endpoint_rejects_invalid_direction(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "sideways", "amount": "10.00", "transaction_date": "2026-09-23"},
    )
    assert response.status_code == 422


# Tests that GET /accounts/{id}/transactions returns deterministic
# newest-first ordering (transaction_date DESC, created_at DESC, id DESC).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if history is ordered by descending
#   transaction_date.
def test_get_account_transactions_endpoint_deterministic_ordering(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)

    client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "credit", "amount": "10.00", "transaction_date": "2026-09-01"},
    )
    client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "credit", "amount": "20.00", "transaction_date": "2026-09-10"},
    )

    response = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    )
    data = response.json()
    assert [t["transaction_date"] for t in data] == ["2026-09-10", "2026-09-01"]


# Tests that includes the opening_balance row alongside subsequent
# adjustments in history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both kinds are present.
def test_get_account_transactions_endpoint_includes_opening_balance(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, opening_balance="200.00")

    create_account_transaction(
        client=client, user_id=user_id, account_id=account["id"], amount="30.00",
    )

    response = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    )
    kinds = {t["kind"] for t in response.json()}
    assert kinds == {"opening_balance", "adjustment"}


# Tests that another user's account transaction history cannot be read.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 404.
def test_get_account_transactions_endpoint_other_user_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    account = create_account(client=client, user_id=other_user_id)

    response = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    )
    assert response.status_code == 404


# Tests that another user cannot create an adjustment against someone
# else's account.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status is 404.
def test_create_account_transaction_endpoint_other_user_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    account = create_account(client=client, user_id=other_user_id)

    response = client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "credit", "amount": "10.00", "transaction_date": "2026-09-23"},
    )
    assert response.status_code == 404


# Tests that there is no PATCH or DELETE route for an individual account
# transaction - corrections must be made through compensating adjustments,
# never edits.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both methods return 405 Method Not Allowed.
def test_account_transaction_has_no_patch_or_delete_route(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)
    transaction = create_account_transaction(
        client=client, user_id=user_id, account_id=account["id"],
    )

    patch_response = client.patch(
        f"/api/v1/accounts/{account['id']}/transactions/{transaction['id']}",
        headers=auth_headers(user_id),
        json={"amount": "999.00"},
    )
    assert patch_response.status_code == 405 or patch_response.status_code == 404

    delete_response = client.delete(
        f"/api/v1/accounts/{account['id']}/transactions/{transaction['id']}",
        headers=auth_headers(user_id),
    )
    assert delete_response.status_code == 405 or delete_response.status_code == 404
