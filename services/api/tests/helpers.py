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

    assert response.status_code == 201

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

    assert response.status_code == 201

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

    assert response.status_code == 201

    return response.json()


# Creates a financial goal through the API for integration tests.
# This helper exists to avoid repeating goal setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: goal name.
# - target_amount: goal target amount.
# - current_amount: already saved amount.
# Returns:
# - Created goal response body.
def create_goal(
    client: TestClient,
    user_id: str,
    name: str = "Vacation",
    target_amount: int = 2000,
    current_amount: int = 500,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/goals",
        headers=auth_headers(user_id),
        json={
            "name": name,
            "target_amount": target_amount,
            "current_amount": current_amount,
            "currency": "EUR",
            "target_date": "2026-12-31",
            "status": "active",
        },
    )

    assert response.status_code == 201

    return response.json()