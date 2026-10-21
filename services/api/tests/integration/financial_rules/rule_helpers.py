from typing import Any, Optional

from fastapi.testclient import TestClient

from tests.helpers import auth_headers

RULES_URL = "/api/v1/financial-rules"


def floor_payload(account_id: str, amount: str = "1000.00", name: str = "Floor") -> dict[str, Any]:
    return {
        "rule_type": "MINIMUM_UNALLOCATED_FLOOR",
        "name": name,
        "source_account_id": account_id,
        "floor_amount": amount,
    }


def overcommitment_payload(account_id: str, name: str = "Overcommitted") -> dict[str, Any]:
    return {"rule_type": "OVERCOMMITMENT_ALERT", "name": name, "source_account_id": account_id}


def budget_alert_payload(budget_id: str, name: str = "Budget watch") -> dict[str, Any]:
    return {"rule_type": "BUDGET_ALERT", "name": name, "budget_id": budget_id}


def allocation_payload(
    account_id: str,
    goal_ids: list[str],
    name: str = "Save",
    policy: str = "FIXED_PER_GOAL",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rule_type": "INCOME_ALLOCATION",
        "name": name,
        "source_account_id": account_id,
        "execution_mode": "AUTO",
        "policy": policy,
        "targets": [
            {"goal_id": goal_id, **({"amount_or_cap": "100.00"} if policy == "FIXED_PER_GOAL" else {})}
            for goal_id in goal_ids
        ],
    }
    if policy == "PERCENT_OF_INCOME_WATERFALL":
        payload["percent"] = "20.00"
    payload.update(overrides)
    return payload


def create_rule(client: TestClient, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(RULES_URL, headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def post_rule(client: TestClient, user_id: str, payload: dict[str, Any]):
    return client.post(RULES_URL, headers=auth_headers(user_id), json=payload)


def patch_rule(client: TestClient, user_id: str, rule_id: str, **fields: Any):
    return client.patch(f"{RULES_URL}/{rule_id}", headers=auth_headers(user_id), json=fields)


def action(client: TestClient, user_id: str, rule_id: str, name: str):
    return client.post(f"{RULES_URL}/{rule_id}/{name}", headers=auth_headers(user_id))


def get_rule(client: TestClient, user_id: str, rule_id: str):
    return client.get(f"{RULES_URL}/{rule_id}", headers=auth_headers(user_id))


def delete_rule(client: TestClient, user_id: str, rule_id: str):
    return client.delete(f"{RULES_URL}/{rule_id}", headers=auth_headers(user_id))


def account_by_id(client: TestClient, user_id: str, account_id: str) -> Optional[dict[str, Any]]:
    for account in client.get("/api/v1/accounts", headers=auth_headers(user_id)).json():
        if account["id"] == account_id:
            return account
    return None
