from typing import Any, Optional, Union

from fastapi.testclient import TestClient


# Builds authentication headers for test requests.
# This helper exists to avoid repeating X-User-Id header creation in every test.
# Parameters:
# - user_id: user identifier as string.
# Returns:
# - Dictionary with authentication headers.
def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


# Creates an expense through the API for integration tests.
# This helper exists to keep test setup short and readable.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - category_id: optional category identifier.
# - title: expense title.
# - amount: expense amount.
# Returns:
# - Created expense response body.
def create_expense(
    client: TestClient,
    user_id: str,
    category_id: Optional[str] = None,
    title: str = "Groceries",
    amount: Union[int, float] = 50,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "title": title,
            "amount": amount,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": title,
            "source": "manual",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a category through the API for integration tests.
# This helper exists to avoid repeating category setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: category name.
# Returns:
# - Created category response body.
def create_category(
    client: TestClient,
    user_id: str,
    name: str = "Food",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/categories",
        headers=auth_headers(user_id),
        json={
            "name": name,
            "color": "#FF5733",
            "icon": "utensils",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a budget through the API for integration tests.
# This helper exists to avoid repeating budget setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - category_id: optional category identifier.
# - name: budget name.
# - limit_amount: budget limit amount.
# Returns:
# - Created budget response body.
def create_budget(
    client: TestClient,
    user_id: str,
    category_id: Optional[str] = None,
    name: str = "Food budget",
    limit_amount: int = 400,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/budgets",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "name": name,
            "limit_amount": limit_amount,
            "currency": "EUR",
            "period": "monthly",
            "start_date": "2026-05-01",
            "end_date": None,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a financial goal through the API for integration tests.
# This helper exists to avoid repeating goal setup code. current_amount is
# not a parameter (VF-016): every new Goal starts at 0 - use
# create_goal_transaction below to fund one.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: goal name.
# - target_amount: goal target amount.
# Returns:
# - Created goal response body.
def create_goal(
    client: TestClient,
    user_id: str,
    name: str = "Vacation",
    target_amount: int = 2000,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/goals",
        headers=auth_headers(user_id),
        json={
            "name": name,
            "target_amount": target_amount,
            "currency": "EUR",
            "target_date": "2026-12-31",
            "status": "active",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a goal transaction (contribution or withdrawal) through the API
# for integration tests.
# This helper exists to avoid repeating transaction setup code, e.g. to
# fund a goal before exercising a scenario that depends on a non-zero
# balance.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - goal_id: financial goal identifier to transact against.
# - amount: transaction amount.
# - type: "contribution" or "withdrawal".
# Returns:
# - Created goal transaction response body.
def create_goal_transaction(
    client: TestClient,
    user_id: str,
    goal_id: str,
    amount: int = 500,
    type: str = "contribution",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/goals/{goal_id}/transactions",
        headers=auth_headers(user_id),
        json={
            "type": type,
            "amount": amount,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates an account through the API for integration tests.
# This helper exists to avoid repeating account setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: account name.
# - type: account type.
# - currency: account currency.
# - opening_balance: optional signed starting balance.
# Returns:
# - Created account response body.
def create_account(
    client: TestClient,
    user_id: str,
    name: str = "Main Checking",
    type: str = "checking",
    currency: str = "EUR",
    opening_balance: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "type": type,
        "currency": currency,
    }

    if opening_balance is not None:
        payload["opening_balance"] = opening_balance

    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(user_id),
        json=payload,
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a manual adjustment account transaction through the API for
# integration tests.
# This helper exists to avoid repeating adjustment setup code, e.g. to
# fund/drain an account before exercising a scenario that depends on a
# specific balance.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - account_id: account identifier to adjust.
# - amount: adjustment amount.
# - direction: "credit" or "debit".
# - transaction_date: date the adjustment happened.
# Returns:
# - Created account transaction response body.
def create_account_transaction(
    client: TestClient,
    user_id: str,
    account_id: str,
    amount: str = "100.00",
    direction: str = "credit",
    transaction_date: str = "2026-09-23",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/accounts/{account_id}/transactions",
        headers=auth_headers(user_id),
        json={
            "direction": direction,
            "amount": amount,
            "transaction_date": transaction_date,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a receipt through the API for integration tests.
# This helper exists to avoid repeating receipt creation request code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - payload: optional custom receipt creation payload.
# Returns:
# - Created receipt response body.
def create_receipt(
    client: TestClient,
    user_id: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    request_payload = (
        payload
        if payload is not None
        else {
            "storage_path": f"receipts/{user_id}/receipt-1.jpg",
        }
    )

    response = client.post(
        "/api/v1/receipts",
        json=request_payload,
        headers=auth_headers(user_id),
    )

    assert response.status_code == 201, response.text

    return response.json()