from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_account, create_expense


# Tests that POST /expenses with account_id creates a linked Expense and
# the response reports the linkage.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response includes account_id and the
#   Account's balance (via GET /accounts) reflects the debit.
def test_create_expense_endpoint_linked_happy_path(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "40.00",
            "currency": "EUR", "expense_date": "2026-09-30",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["account_id"] == account["id"]

    accounts_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert accounts_response.json()[0]["current_balance"] == "-40.00"


# Tests that POST /expenses with an archived Account's id is rejected
# with 409 and the exact existing Account error message.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 409 with that message.
def test_create_expense_endpoint_archived_account_rejected(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")
    client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id), json={"status": "archived"},
    )

    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-30",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Archived account cannot receive new transactions."


# Tests that POST /expenses with a currency-mismatched Account is
# rejected with 422 and the exact documented error message.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422 with that message.
def test_create_expense_endpoint_currency_mismatch_rejected(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="USD")

    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-30",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Expense currency must match the account's currency to link them."
    )


# Tests attach/detach/move via PATCH /expenses/{id}.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each step reports the correct account_id and
#   Account balances update accordingly.
def test_update_expense_endpoint_attach_detach_move(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account_a = create_account(client=client, user_id=user_id, name="A", currency="EUR")
    account_b = create_account(client=client, user_id=user_id, name="B", currency="EUR")
    expense = create_expense(client=client, user_id=user_id, amount=30)

    # Attach.
    attach_response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        headers=auth_headers(user_id), json={"account_id": account_a["id"]},
    )
    assert attach_response.status_code == 200
    assert attach_response.json()["account_id"] == account_a["id"]

    accounts = {a["id"]: a for a in client.get(
        "/api/v1/accounts", headers=auth_headers(user_id),
    ).json()}
    assert accounts[account_a["id"]]["current_balance"] == "-30.00"

    # Move.
    move_response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        headers=auth_headers(user_id), json={"account_id": account_b["id"]},
    )
    assert move_response.status_code == 200
    assert move_response.json()["account_id"] == account_b["id"]

    accounts = {a["id"]: a for a in client.get(
        "/api/v1/accounts", headers=auth_headers(user_id),
    ).json()}
    assert accounts[account_a["id"]]["current_balance"] == "0.00"
    assert accounts[account_b["id"]]["current_balance"] == "-30.00"

    # Detach.
    detach_response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        headers=auth_headers(user_id), json={"account_id": None},
    )
    assert detach_response.status_code == 200
    assert detach_response.json()["account_id"] is None

    accounts = {a["id"]: a for a in client.get(
        "/api/v1/accounts", headers=auth_headers(user_id),
    ).json()}
    assert accounts[account_b["id"]]["current_balance"] == "0.00"


# Tests that GET /expenses exposes account_id correctly for a mix of
# linked and unlinked records.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the linked record reports the Account and
#   the unlinked one reports null.
def test_get_expenses_endpoint_exposes_account_id(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    create_expense(client=client, user_id=user_id, title="Cash tip", amount=5)

    response = client.get("/api/v1/expenses", headers=auth_headers(user_id))
    by_title = {item["title"]: item for item in response.json()}
    assert by_title["Groceries"]["account_id"] == account["id"]
    assert by_title["Cash tip"]["account_id"] is None


# Tests that deleting a linked Expense cascades its projection and the
# Account balance drops correctly, with no orphaned transaction visible
# in the Account's history.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the Account balance returns to 0 and the
#   history endpoint returns an empty list.
def test_delete_expense_endpoint_linked_cascades_projection(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    create_response = client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "40.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    expense_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/expenses/{expense_id}", headers=auth_headers(user_id),
    )
    assert delete_response.status_code == 204

    accounts_response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert accounts_response.json()[0]["current_balance"] == "0.00"

    history_response = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    )
    assert history_response.json() == []


# Tests that another user cannot link their Expense to someone else's
# Account.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 404.
def test_create_expense_endpoint_cross_user_account_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    other_account = create_account(client=client, user_id=other_user_id, currency="EUR")

    response = client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": other_account["id"],
        },
    )
    assert response.status_code == 404


# Tests that an Account's currency becomes immutable once a linked
# Expense has established transaction history - reusing the existing,
# unmodified has_transactions_for_account check, now automatically
# covering Expense-backed rows too.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the currency change is rejected with 409.
def test_account_currency_immutable_after_linked_expense(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )

    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=auth_headers(user_id), json={"currency": "USD"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Account currency cannot be changed after transaction history exists."
    )


# Tests that an Account with linked-Expense history cannot be
# hard-deleted - reusing the existing, unmodified
# has_transactions_for_account check.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the delete is rejected with 409.
def test_account_hard_delete_blocked_by_linked_expense_history(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )

    response = client.delete(
        f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Account with transaction history cannot be deleted. Archive it instead."
    )


# Tests that GET /accounts/{id}/transactions exposes kind="expense" and
# expense_id for a linked-Expense-backed row, and null expense_id for a
# direct adjustment row on the same Account - proving both are present
# and structurally distinguishable in the same response.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both rows have the expected kind/expense_id
#   shape.
def test_account_history_endpoint_exposes_expense_kind_and_expense_id(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id, currency="EUR")

    expense_response = client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={
            "category_id": None, "title": "Groceries", "amount": "10.00",
            "currency": "EUR", "expense_date": "2026-09-01",
            "description": None, "source": "manual", "account_id": account["id"],
        },
    )
    expense_id = expense_response.json()["id"]

    client.post(
        f"/api/v1/accounts/{account['id']}/transactions",
        headers=auth_headers(user_id),
        json={"direction": "credit", "amount": "5.00", "transaction_date": "2026-09-02"},
    )

    history = client.get(
        f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(user_id),
    ).json()

    by_kind = {row["kind"]: row for row in history}
    assert by_kind["expense"]["expense_id"] == expense_id
    assert by_kind["expense"]["income_id"] is None
    assert by_kind["expense"]["direction"] == "debit"
    assert by_kind["adjustment"]["expense_id"] is None
