from datetime import date
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import SessionLocal, engine
from app.modules.goals import goal_service
from tests.helpers import auth_headers, create_account, create_goal, create_goal_transaction

# VF-GOALS-PLANNING-001: POST /api/v1/goals/{goal_id}/plan. A read-only,
# authenticated, ownership-scoped preview. "Today" is frozen so every date in
# the response is exact; the arithmetic itself is covered by the unit tests.

TODAY = date(2026, 11, 16)

# The date an Account's opening balance is as of. The backend defaults it to the REAL
# current date, but these tests evaluate everything as of the frozen TODAY: an Account
# opened "after" that date would have no balance to reserve from, and its opening
# balance would even post after the 2026 ledger events below. A fixed date before every
# other fixture keeps the test independent of the wall clock.
OPENING_BALANCE_DATE = "2026-01-01"


class FrozenDate(date):
    @classmethod
    def today(cls) -> "FrozenDate":
        return cls(TODAY.year, TODAY.month, TODAY.day)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(goal_service, "date", FrozenDate)


def _goal(client: TestClient, user_id: str, *, target: str = "2000.00", target_date: Optional[str] = "2027-03-31", currency: str = "EUR") -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Trip", "target_amount": target, "currency": currency, "status": "active"}

    if target_date is not None:
        payload["target_date"] = target_date

    response = client.post("/api/v1/goals", headers=auth_headers(user_id), json=payload)

    assert response.status_code == 201, response.text

    return response.json()


def _plan(client: TestClient, user_id: str, goal_id: str, body: Optional[dict] = None):
    return client.post(f"/api/v1/goals/{goal_id}/plan", headers=auth_headers(user_id), json=body)


class TestPlanResponse:
    def test_plan_without_a_what_if(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=500)

        response = _plan(client, user_id, goal["id"], {})
        body = response.json()

        assert response.status_code == 200, response.text
        assert body["goal_id"] == goal["id"]
        assert body["currency"] == "EUR"
        assert body["as_of"] == "2026-11-16"
        assert body["target_amount"] == "2000.00"
        assert body["current_amount"] == "500.00"
        assert body["tracked_amount"] == "500.00"
        assert body["linked_amount"] == "0.00"
        assert body["remaining_amount"] == "1500.00"
        assert body["overfunded_amount"] == "0.00"
        assert body["target_date"] == "2027-03-31"
        assert body["plan_status"] == "ready"
        assert body["installment_count"] == 5  # Nov 16, Dec 1, Jan 1, Feb 1, Mar 1
        assert body["required_per_installment"] == "300.00"
        assert body["first_installment_date"] == "2026-11-16"
        assert body["last_installment_date"] == "2027-03-01"
        assert body["horizon_months"] == 600
        assert body["what_if"] is None

    def test_a_request_without_any_body_is_the_plan_alone(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        response = client.post(f"/api/v1/goals/{goal['id']}/plan", headers=auth_headers(user_id))

        assert response.status_code == 200, response.text
        assert response.json()["what_if"] is None

    def test_what_if_projection(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target="450.00", target_date="2027-03-01")

        body = _plan(client, user_id, goal["id"], {"monthly_contribution": "100.00"}).json()

        assert body["what_if"] == {
            "monthly_contribution": "100.00",
            "outcome": "reaches_target",
            "installments_needed": 5,
            "estimated_completion_date": "2027-03-01",
            "on_or_before_target_date": True,
        }

    def test_progress_is_the_ledger_derived_amount_with_tracked_and_linked_apart(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target="1000.00")
        account = create_account(client, user_id, opening_balance="800.00", opening_balance_date=OPENING_BALANCE_DATE)
        create_goal_transaction(client, user_id, goal["id"], amount=300)  # tracked
        linked = client.post(
            f"/api/v1/goals/{goal['id']}/transactions",
            headers=auth_headers(user_id),
            json={"type": "contribution", "amount": "200.00", "account_id": account["id"], "client_request_id": str(uuid4())},
        )
        assert linked.status_code == 201, linked.text

        body = _plan(client, user_id, goal["id"], {}).json()
        goal_read = next(item for item in client.get("/api/v1/goals", headers=auth_headers(user_id)).json() if item["id"] == goal["id"])

        assert (body["tracked_amount"], body["linked_amount"], body["current_amount"]) == ("300.00", "200.00", "500.00")
        assert body["current_amount"] == goal_read["current_amount"]  # one balance source
        assert body["remaining_amount"] == "500.00"

    def test_no_target_date_overfunded_and_archived_goals(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        no_date = _goal(client, user_id, target_date=None)
        over = _goal(client, user_id, target="100.00")
        create_goal_transaction(client, user_id, over["id"], amount=150)
        archived = _goal(client, user_id)
        assert client.patch(f"/api/v1/goals/{archived['id']}", headers=auth_headers(user_id), json={"status": "archived"}).status_code == 200

        no_date_body = _plan(client, user_id, no_date["id"], {}).json()
        over_body = _plan(client, user_id, over["id"], {"monthly_contribution": "10.00"}).json()
        archived_body = _plan(client, user_id, archived["id"], {"monthly_contribution": "10.00"}).json()

        assert (no_date_body["plan_status"], no_date_body["required_per_installment"], no_date_body["installment_count"]) == ("no_target_date", None, None)
        assert (over_body["plan_status"], over_body["remaining_amount"], over_body["overfunded_amount"]) == ("already_funded", "0.00", "50.00")
        assert over_body["what_if"]["outcome"] == "already_funded"
        assert (archived_body["plan_status"], archived_body["what_if"]["outcome"]) == ("archived", "not_applicable")

    def test_a_past_target_date_is_explained_not_planned(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target_date="2026-11-15")

        body = _plan(client, user_id, goal["id"], {"monthly_contribution": "100.00"}).json()

        assert body["plan_status"] == "target_date_passed"
        assert body["required_per_installment"] is None
        assert body["what_if"]["outcome"] == "reaches_target"
        assert body["what_if"]["on_or_before_target_date"] is None

    def test_zero_and_huge_contributions_are_safe(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target="2000.00")

        zero = _plan(client, user_id, goal["id"], {"monthly_contribution": "0"}).json()
        huge = _plan(client, user_id, goal["id"], {"monthly_contribution": "9999999999.99"}).json()
        tiny = _plan(client, user_id, goal["id"], {"monthly_contribution": "0.01"}).json()

        assert zero["what_if"]["outcome"] == "no_contribution"
        assert (huge["what_if"]["installments_needed"], huge["what_if"]["estimated_completion_date"]) == (1, "2026-11-16")
        assert tiny["what_if"]["outcome"] == "not_reachable_within_horizon"


class TestInputValidation:
    @pytest.mark.parametrize(
        "value",
        ["-1.00", "-0.01", "10.005", "abc", "NaN", "Infinity", "-Infinity", "1e400", "99999999999999.99", "", [], {}, True],
    )
    def test_invalid_contributions_are_rejected_without_a_calculation(self, client: TestClient, clean_database: None, value: Any) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        response = _plan(client, user_id, goal["id"], {"monthly_contribution": value})

        assert response.status_code == 422, (value, response.text)

    def test_unknown_fields_are_rejected(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        assert _plan(client, user_id, goal["id"], {"monthly_contribution": "10.00", "as_of": "2020-01-01"}).status_code == 422
        assert _plan(client, user_id, goal["id"], {"current_amount": "999.00"}).status_code == 422


class TestAuthenticationAndOwnership:
    def test_requires_authentication(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        assert client.post(f"/api/v1/goals/{goal['id']}/plan", json={}).status_code == 401

    def test_another_users_goal_looks_exactly_like_a_missing_goal(self, client: TestClient, clean_database: None) -> None:
        owner, intruder = str(uuid4()), str(uuid4())
        goal = _goal(client, owner)

        foreign = _plan(client, intruder, goal["id"], {})
        missing = _plan(client, intruder, str(uuid4()), {})

        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert foreign.json()["detail"] == "Goal not found."
        assert goal["name"] not in foreign.text

    def test_a_malformed_goal_id_is_a_validation_error(self, client: TestClient, clean_database: None) -> None:
        assert client.post("/api/v1/goals/not-a-uuid/plan", headers=auth_headers(str(uuid4())), json={}).status_code == 422


class TestReadOnly:
    def test_the_request_executes_no_write_and_takes_no_lock(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=100)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = _plan(client, user_id, goal["id"], {"monthly_contribution": "50.00"})
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200, response.text
        assert statements, "the request must have read the database"
        for statement in statements:
            assert statement.startswith("SELECT"), statement
            assert "FOR UPDATE" not in statement and "FOR SHARE" not in statement, statement

    def test_the_stored_data_is_identical_before_and_after(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=100)

        def snapshot() -> list[Any]:
            with SessionLocal() as session:
                return [
                    session.execute(text("SELECT id::text, updated_at::text, priority_rank FROM goals ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, type FROM goal_transactions ORDER BY id")).all(),
                    session.execute(text("SELECT count(*) FROM account_transactions")).scalar_one(),
                    session.execute(text("SELECT count(*) FROM rule_executions")).scalar_one(),
                ]

        before = snapshot()

        for body in ({}, {"monthly_contribution": "25.00"}, {"monthly_contribution": "0"}):
            assert _plan(client, user_id, goal["id"], body).status_code == 200

        assert snapshot() == before
        assert len(client.get(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id)).json()) == 1
