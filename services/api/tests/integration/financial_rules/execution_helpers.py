from datetime import date
from typing import Any, Optional

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import engine
from tests.helpers import auth_headers, create_account
from tests.integration.financial_rules.rule_helpers import (
    RULES_URL,
    action,
    allocation_payload,
    create_rule,
)

EVALUATE_URL = f"{RULES_URL}/evaluate"
EXECUTIONS_URL = "/api/v1/rule-executions"


def goal_with_target(client: TestClient, user_id: str, name: str, target: int, currency: str = "EUR") -> dict[str, Any]:
    response = client.post(
        "/api/v1/goals",
        headers=auth_headers(user_id),
        json={"name": name, "target_amount": target, "currency": currency, "status": "active"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def funded_account(client: TestClient, user_id: str, opening: str = "5000.00", currency: str = "EUR") -> dict[str, Any]:
    return create_account(client, user_id, currency=currency, opening_balance=opening)


def enabled_rule(
    client: TestClient, user_id: str, account_id: str, goal_ids: list[str],
    policy: str = "FIXED_PER_GOAL", **overrides: Any,
) -> dict[str, Any]:
    rule = create_rule(client, user_id, allocation_payload(account_id, goal_ids, policy=policy, **overrides))
    response = action(client, user_id, rule["id"], "enable")
    assert response.status_code == 200, response.text
    return response.json()


def post_income(
    client: TestClient, user_id: str, amount: str, account_id: Optional[str],
    received_at: Optional[date] = None, source: str = "salary", currency: str = "EUR",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "amount": amount, "currency": currency,
        "received_at": (received_at or date.today()).isoformat(), "source": source,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    response = client.post("/api/v1/income", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def evaluate(client: TestClient, user_id: str, limit: Optional[int] = None):
    suffix = f"?limit={limit}" if limit is not None else ""
    return client.post(EVALUATE_URL + suffix, headers=auth_headers(user_id))


def executions(client: TestClient, user_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(EXECUTIONS_URL, headers=auth_headers(user_id), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def account_view(client: TestClient, user_id: str, account_id: str) -> dict[str, Any]:
    for account in client.get("/api/v1/accounts", headers=auth_headers(user_id)).json():
        if account["id"] == account_id:
            return account
    raise AssertionError("account not found")


def goal_view(client: TestClient, user_id: str, goal_id: str) -> dict[str, Any]:
    response = client.get("/api/v1/goals", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    for goal in response.json():
        if goal["id"] == goal_id:
            return goal
    raise AssertionError("goal not found")


def scalar(sql: str, **params: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()
