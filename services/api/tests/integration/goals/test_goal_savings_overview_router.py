from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import SessionLocal, engine
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.financial_settings.financial_settings_models import UserFinancialSettingsModel
from app.modules.goals import goal_service
from tests.helpers import auth_headers, create_account, create_account_transaction, create_goal_transaction

# VF-GOALS-PLANNING-002B: GET /api/v1/goals/savings-overview. A read-only,
# authenticated, user-scoped overview of the combined hypothetical installments
# of every planned Goal, month by month, compared with the recorded history of
# the last three COMPLETED months. "Today" is frozen at 2026-11-16, so the
# completed months are August, September and October 2026. The arithmetic is
# covered by the unit tests; these tests prove the wiring, the data, isolation
# and that nothing is written.

TODAY = date(2026, 11, 16)

# The date an Account's opening balance is as of. The backend defaults it to the REAL
# current date, but these tests evaluate everything as of the frozen TODAY: an Account
# opened "after" that date would have no balance to reserve from, and its opening
# balance would even post after the 2026 ledger events below. A fixed date before every
# other fixture keeps the test independent of the wall clock.
OPENING_BALANCE_DATE = "2026-01-01"


def _freeze(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(goal_service, "date", FrozenDate)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, TODAY)


def _goal(
    client: TestClient,
    user_id: str,
    name: str = "Goal",
    *,
    target: str = "1000.00",
    target_date: Optional[str] = "2027-03-31",
    currency: str = "EUR",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "target_amount": target, "currency": currency, "status": "active"}

    if target_date is not None:
        payload["target_date"] = target_date

    response = client.post("/api/v1/goals", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text

    return response.json()


def _set_status(client: TestClient, user_id: str, goal_id: str, status: str) -> None:
    assert client.patch(f"/api/v1/goals/{goal_id}", headers=auth_headers(user_id), json={"status": status}).status_code == 200


def _income(client: TestClient, user_id: str, amount: str, received_at: str, account_id: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"amount": amount, "currency": "EUR", "received_at": received_at, "source": "salary"}

    if account_id is not None:
        payload["account_id"] = account_id

    assert client.post("/api/v1/income", headers=auth_headers(user_id), json=payload).status_code == 201


def _expense(client: TestClient, user_id: str, amount: str, expense_date: str, account_id: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"title": "Spend", "amount": amount, "currency": "EUR", "expense_date": expense_date, "source": "manual"}

    if account_id is not None:
        payload["account_id"] = account_id

    assert client.post("/api/v1/expenses", headers=auth_headers(user_id), json=payload).status_code == 201


def _three_months(client: TestClient, user_id: str, income: str = "3000.00", expense: str = "2400.00") -> None:
    for month in ("2026-08-15", "2026-09-15", "2026-10-15"):
        _income(client, user_id, income, month)
        _expense(client, user_id, expense, month)


def _overview(client: TestClient, user_id: str):
    return client.get("/api/v1/goals/savings-overview", headers=auth_headers(user_id))


def _totals(body: dict[str, Any]) -> list[str]:
    return [month["total_required"] for month in body["months"]]


class TestCombinedOverview:
    def test_several_goals_are_added_month_by_month_and_compared_with_history(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        # as_of 2026-11-16: installments Nov 16, Dec 1, Jan 1, Feb 1, Mar 1.
        long_goal = _goal(client, user_id, "Long", target="1000.00", target_date="2027-03-31")  # 5 x 200.00
        short_goal = _goal(client, user_id, "Short", target="600.00", target_date="2026-12-20")  # 2 x 300.00
        _three_months(client, user_id)  # net 600.00 / month

        response = _overview(client, user_id)
        body = response.json()

        assert response.status_code == 200, response.text
        assert body["as_of"] == "2026-11-16"
        assert body["base_currency"] == "EUR"
        assert body["horizon_months"] == 12 and len(body["months"]) == 12
        assert body["is_total_complete"] is True
        assert [g["name"] for g in body["planned_goals"]] == ["Long", "Short"]
        assert _totals(body) == ["500.00", "500.00", "200.00", "200.00", "200.00"] + ["0.00"] * 7
        assert [m["planned_goal_count"] for m in body["months"][:6]] == [2, 2, 1, 1, 1, 0]
        assert body["months"][0]["contributions"] == [
            {"goal_id": long_goal["id"], "amount": "200.00"},
            {"goal_id": short_goal["id"], "amount": "300.00"},
        ]
        assert body["history"]["status"] == "comparable"
        assert body["history"]["average_monthly_net_flow"] == "600.00"
        assert [m["historical_difference"] for m in body["months"][:6]] == ["100.00", "100.00", "400.00", "400.00", "400.00", None]
        assert [m["difference_direction"] for m in body["months"][:6]] == ["surplus", "surplus", "surplus", "surplus", "surplus", None]
        assert body["limitations"] == ["budgets_not_modelled", "goal_commitments_not_modelled", "future_obligations_not_modelled"]

    def test_the_month_boundaries_follow_the_calendar(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())

        body = _overview(client, user_id).json()

        assert body["months"][0]["period_start"] == "2026-11-01"
        assert body["months"][0]["period_end"] == "2026-11-30"
        assert body["months"][0]["installment_date"] == "2026-11-16"
        assert body["months"][1]["installment_date"] == "2026-12-01"
        assert body["months"][2]["period_start"] == "2027-01-01"
        assert body["months"][11]["period_end"] == "2027-10-31"

    def test_a_leap_day_as_of_date(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        _freeze(monkeypatch, date(2028, 2, 29))
        user_id = str(uuid4())
        _goal(client, user_id, "Leap", target="200.00", target_date="2028-03-01")  # installments Feb 29 and Mar 1

        body = _overview(client, user_id).json()

        assert body["months"][0]["period_end"] == "2028-02-29"
        assert body["months"][0]["installment_date"] == "2028-02-29"
        assert body["months"][1]["installment_date"] == "2028-03-01"
        assert _totals(body)[:3] == ["100.00", "100.00", "0.00"]
        assert body["history"]["analysis_period_start"] == "2027-11-01"
        assert body["history"]["analysis_period_end"] == "2028-01-31"

    def test_priorities_decide_the_display_order_and_follow_a_reorder(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        first = _goal(client, user_id, "First")
        second = _goal(client, user_id, "Second")
        third = _goal(client, user_id, "Third")

        assert [g["name"] for g in _overview(client, user_id).json()["planned_goals"]] == ["First", "Second", "Third"]

        reorder = client.put(
            "/api/v1/goals/priorities",
            headers=auth_headers(user_id),
            json={"goal_ids": [third["id"], first["id"], second["id"]]},
        )
        assert reorder.status_code == 200, reorder.text

        body = _overview(client, user_id).json()

        assert [g["name"] for g in body["planned_goals"]] == ["Third", "First", "Second"]
        assert [g["priority_rank"] for g in body["planned_goals"]] == [1, 2, 3]
        assert [c["goal_id"] for c in body["months"][0]["contributions"]] == [third["id"], first["id"], second["id"]]

    def test_the_installment_is_the_goal_plan_s_own(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target="1234.56", target_date="2027-06-30")
        create_goal_transaction(client, user_id, goal["id"], amount=100)

        plan = client.post(f"/api/v1/goals/{goal['id']}/plan", headers=auth_headers(user_id), json={}).json()
        item = _overview(client, user_id).json()["planned_goals"][0]

        assert item["required_per_installment"] == plan["required_per_installment"]
        assert item["installment_count"] == plan["installment_count"]
        assert item["remaining_amount"] == plan["remaining_amount"]
        assert (item["first_installment_date"], item["last_installment_date"]) == (plan["first_installment_date"], plan["last_installment_date"])


class TestExcludedGoals:
    def test_funded_overfunded_archived_completed_undated_and_overdue_goals(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        planned = _goal(client, user_id, "Planned", target="500.00", target_date="2026-11-30")
        funded = _goal(client, user_id, "Funded", target="100.00")
        create_goal_transaction(client, user_id, funded["id"], amount=100)
        over = _goal(client, user_id, "Over", target="100.00")
        create_goal_transaction(client, user_id, over["id"], amount=150)
        archived = _goal(client, user_id, "Archived")
        _set_status(client, user_id, archived["id"], "archived")
        completed = _goal(client, user_id, "Completed")
        _set_status(client, user_id, completed["id"], "completed")
        _goal(client, user_id, "Undated", target_date=None)
        _goal(client, user_id, "Overdue", target_date="2026-11-15")
        _three_months(client, user_id)

        body = _overview(client, user_id).json()

        assert [g["name"] for g in body["planned_goals"]] == ["Planned"]
        assert planned["id"] == body["planned_goals"][0]["goal_id"]
        assert body["exclusions"] == {
            "archived": 1,
            "completed": 1,
            "already_funded": 2,
            "no_target_date": 1,
            "target_date_passed": 1,
            "other_currency": 0,
            "other_currencies": [],
        }
        assert _totals(body)[:2] == ["500.00", "0.00"]
        assert body["limitations"] == [
            "goals_without_target_date",
            "goals_with_passed_target_date",
            "budgets_not_modelled",
            "goal_commitments_not_modelled",
            "future_obligations_not_modelled",
        ]

    def test_a_user_with_only_unplanned_goals_has_no_requirement_and_no_comparison(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id, target_date=None)
        _three_months(client, user_id)

        body = _overview(client, user_id).json()

        assert body["planned_goals"] == []
        assert body["history"]["status"] == "no_planned_goals"
        assert set(_totals(body)) == {"0.00"}
        assert all(m["historical_difference"] is None for m in body["months"])

    def test_a_new_user_gets_an_empty_overview(self, client: TestClient, clean_database: None) -> None:
        body = _overview(client, str(uuid4())).json()

        assert body["planned_goals"] == [] and len(body["months"]) == 12
        assert body["is_total_complete"] is True
        assert body["history"]["status"] == "no_planned_goals"


class TestMixedCurrencies:
    def test_goals_in_another_currency_are_excluded_and_the_total_is_incomplete(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id, "Eur", target="500.00", target_date="2026-11-30")
        _goal(client, user_id, "Usd", target="900.00", target_date="2026-11-30", currency="USD")
        _goal(client, user_id, "Gbp", target="700.00", target_date="2026-11-30", currency="GBP")
        _three_months(client, user_id)

        body = _overview(client, user_id).json()

        assert [g["name"] for g in body["planned_goals"]] == ["Eur"]
        assert body["months"][0]["total_required"] == "500.00"  # 900 USD and 700 GBP are never added or converted
        assert body["exclusions"]["other_currency"] == 2
        assert body["exclusions"]["other_currencies"] == ["GBP", "USD"]
        assert body["is_total_complete"] is False
        assert "other_currency_goals_excluded" in body["limitations"]

    def test_the_base_currency_is_the_one_in_the_user_s_settings(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id, "Eur", target="500.00", target_date="2026-11-30")
        _goal(client, user_id, "Usd", target="300.00", target_date="2026-11-30", currency="USD")
        with SessionLocal() as session:
            session.add(UserFinancialSettingsModel(user_id=user_id, base_currency="USD"))
            session.commit()

        body = _overview(client, user_id).json()

        assert body["base_currency"] == "USD"
        assert [g["name"] for g in body["planned_goals"]] == ["Usd"]
        assert body["exclusions"]["other_currencies"] == ["EUR"]


class TestHistoricalData:
    def test_negative_net_flow_is_a_shortfall(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id, target="500.00", target_date="2026-11-30")
        _three_months(client, user_id, income="1000.00", expense="1500.00")

        body = _overview(client, user_id).json()

        assert body["history"]["average_monthly_net_flow"] == "-500.00"
        assert body["months"][0]["historical_difference"] == "-1000.00"
        assert body["months"][0]["difference_direction"] == "shortfall"

    def test_no_history_is_insufficient_not_zero_obligations(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id, target="500.00", target_date="2026-11-30")

        body = _overview(client, user_id).json()

        assert body["history"]["status"] == "insufficient_data"
        assert (body["history"]["average_monthly_net_flow"], body["months"][0]["historical_difference"]) == (None, None)
        assert body["months"][0]["total_required"] == "500.00"
        assert "fewer_than_two_active_months" in body["limitations"]
        assert [m["has_activity"] for m in body["history"]["months"]] == [False, False, False]

    def test_a_single_active_month_is_insufficient(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id)
        _income(client, user_id, "3000.00", "2026-10-15")
        _expense(client, user_id, "2400.00", "2026-10-15")

        assert _overview(client, user_id).json()["history"]["status"] == "insufficient_data"

    def test_the_current_month_and_older_months_are_not_analysed(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id)
        _three_months(client, user_id)
        _income(client, user_id, "99999.00", "2026-11-02")  # the month in progress
        _income(client, user_id, "99999.00", "2026-07-20")  # older than the three completed months

        body = _overview(client, user_id).json()

        assert [m["period_start"] for m in body["history"]["months"]] == ["2026-08-01", "2026-09-01", "2026-10-01"]
        assert body["history"]["average_monthly_net_flow"] == "600.00"

    def test_an_unresolved_record_blocks_the_comparison(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id)
        _three_months(client, user_id)
        with SessionLocal() as session:
            session.add(ExpenseModel(
                user_id=user_id, category_id=None, title="Legacy USD", amount=Decimal("999.00"),
                currency="USD", expense_date=date(2026, 9, 20), source="manual",
            ))
            session.commit()

        body = _overview(client, user_id).json()

        assert body["history"]["status"] == "insufficient_data"
        assert "unresolved_currency_data" in body["limitations"]
        assert all(m["historical_difference"] is None for m in body["months"])


class TestNoDoubleCounting:
    def test_progress_reservations_and_balances_are_never_income_expenses_or_monthly_obligations(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        account = create_account(client, user_id, opening_balance="5000.00", opening_balance_date=OPENING_BALANCE_DATE)
        goal = _goal(client, user_id, target="1000.00", target_date="2027-03-31")
        create_goal_transaction(client, user_id, goal["id"], amount=300)  # tracked progress
        reserved = client.post(
            f"/api/v1/goals/{goal['id']}/transactions",
            headers=auth_headers(user_id),
            json={"type": "contribution", "amount": "200.00", "account_id": account["id"], "client_request_id": str(uuid4())},
        )
        assert reserved.status_code == 201, reserved.text
        create_account_transaction(client, user_id, account["id"], amount="750.00")  # a manual Account adjustment
        _three_months(client, user_id)

        body = _overview(client, user_id).json()

        assert body["history"]["average_monthly_net_flow"] == "600.00"  # untouched by balances, adjustments or Goal money
        assert body["planned_goals"][0]["remaining_amount"] == "500.00"  # 1000 - (300 tracked + 200 linked), each counted once
        assert body["planned_goals"][0]["required_per_installment"] == "100.00"
        assert _totals(body)[:5] == ["100.00"] * 5

    def test_an_account_linked_income_and_expense_is_counted_once(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        account = create_account(client, user_id, opening_balance="0.00")
        _goal(client, user_id)
        for month in ("2026-08-15", "2026-09-15", "2026-10-15"):
            _income(client, user_id, "3000.00", month, account_id=account["id"])
            _expense(client, user_id, "2400.00", month, account_id=account["id"])

        assert _overview(client, user_id).json()["history"]["average_monthly_net_flow"] == "600.00"

    def test_each_goal_appears_once_per_month(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        for index in range(4):
            _goal(client, user_id, f"G{index}", target=f"{(index + 1) * 100}.00")

        for month in _overview(client, user_id).json()["months"]:
            ids = [c["goal_id"] for c in month["contributions"]]

            assert len(ids) == len(set(ids)) == month["planned_goal_count"]


class TestAuthenticationAndIsolation:
    def test_requires_authentication(self, client: TestClient, clean_database: None) -> None:
        assert client.get("/api/v1/goals/savings-overview").status_code == 401

    def test_another_user_s_goals_and_records_never_enter_the_overview(self, client: TestClient, clean_database: None) -> None:
        owner, other = str(uuid4()), str(uuid4())
        _goal(client, owner, "Mine", target="500.00", target_date="2026-11-30")
        _three_months(client, owner)
        _goal(client, other, "Theirs", target="9000.00", target_date="2026-11-30")
        _income(client, other, "50000.00", "2026-10-01")
        _expense(client, other, "1.00", "2026-10-01")

        body = _overview(client, owner).json()

        assert [g["name"] for g in body["planned_goals"]] == ["Mine"]
        assert body["months"][0]["total_required"] == "500.00"
        assert body["history"]["average_monthly_net_flow"] == "600.00"
        assert "Theirs" not in str(_overview(client, owner).text)

    def test_the_static_path_is_not_captured_as_a_goal_id(self, client: TestClient, clean_database: None) -> None:
        assert _overview(client, str(uuid4())).status_code == 200


class TestReadOnly:
    def test_a_new_user_s_request_executes_no_write_and_creates_no_settings_row(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        _goal(client, user_id)
        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user_id}).scalar_one() == 0

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = _overview(client, user_id)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200, response.text
        assert statements, "the request must have read the database"
        for statement in statements:
            assert statement.startswith("SELECT"), statement
            assert "FOR UPDATE" not in statement and "FOR SHARE" not in statement, statement

        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user_id}).scalar_one() == 0

    def test_the_stored_data_is_identical_before_and_after(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        _goal(client, user_id, "Other", currency="USD")
        _three_months(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=100)

        def snapshot() -> list[Any]:
            with SessionLocal() as session:
                return [
                    session.execute(text("SELECT id::text, updated_at::text, priority_rank, status FROM goals ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, type FROM goal_transactions ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, base_amount::text FROM income ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, base_amount::text FROM expenses ORDER BY id")).all(),
                    session.execute(text("SELECT count(*) FROM account_transactions")).scalar_one(),
                    session.execute(text("SELECT count(*) FROM rule_executions")).scalar_one(),
                    session.execute(text("SELECT count(*) FROM user_financial_settings")).scalar_one(),
                ]

        before = snapshot()

        for _ in range(2):
            assert _overview(client, user_id).status_code == 200

        assert snapshot() == before


class TestQueryCount:
    def test_the_number_of_queries_does_not_grow_with_the_number_of_goals(self, client: TestClient, clean_database: None) -> None:
        def count_statements(user_id: str) -> int:
            statements: list[str] = []

            def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                assert _overview(client, user_id).status_code == 200
            finally:
                event.remove(engine, "before_cursor_execute", record)

            return len(statements)

        few, many = str(uuid4()), str(uuid4())
        _goal(client, few)
        for index in range(8):
            goal = _goal(client, many, f"G{index}", target=f"{(index + 1) * 100}.00")
            create_goal_transaction(client, many, goal["id"], amount=10)
        _goal(client, many, "Usd", currency="USD")

        assert count_statements(many) == count_statements(few)
