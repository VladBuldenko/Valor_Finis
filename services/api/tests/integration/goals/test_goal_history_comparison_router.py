from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import SessionLocal, engine
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.goals import goal_service
from tests.helpers import auth_headers, create_account, create_account_transaction, create_account_transfer, create_goal_transaction

# VF-GOALS-PLANNING-002A: GET /api/v1/goals/{goal_id}/plan/history-comparison.
# A read-only, authenticated, ownership-scoped comparison of the Goal plan's
# required installment with the recorded income and expenses of the last three
# COMPLETED months. "Today" is frozen at 2026-11-16, so the completed months are
# August, September and October 2026; November (in progress) and July (older)
# are outside. The arithmetic itself is covered by the unit tests.

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


def _goal(
    client: TestClient,
    user_id: str,
    *,
    target: str = "2250.00",
    target_date: Optional[str] = "2027-03-31",
    currency: str = "EUR",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Trip", "target_amount": target, "currency": currency, "status": "active"}

    if target_date is not None:
        payload["target_date"] = target_date

    response = client.post("/api/v1/goals", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text

    return response.json()


def _income(client: TestClient, user_id: str, amount: str, received_at: str, account_id: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"amount": amount, "currency": "EUR", "received_at": received_at, "source": "salary"}

    if account_id is not None:
        payload["account_id"] = account_id

    response = client.post("/api/v1/income", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text


def _expense(client: TestClient, user_id: str, amount: str, expense_date: str, account_id: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"title": "Spend", "amount": amount, "currency": "EUR", "expense_date": expense_date, "source": "manual"}

    if account_id is not None:
        payload["account_id"] = account_id

    response = client.post("/api/v1/expenses", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text


def _three_months(client: TestClient, user_id: str, income: str = "3000.00", expense: str = "2400.00") -> None:
    for month in ("2026-08-15", "2026-09-15", "2026-10-15"):
        _income(client, user_id, income, month)
        _expense(client, user_id, expense, month)


def _compare(client: TestClient, user_id: str, goal_id: str):
    return client.get(f"/api/v1/goals/{goal_id}/plan/history-comparison", headers=auth_headers(user_id))


class TestComparison:
    def test_recorded_history_is_compared_with_the_required_installment(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)  # 2250.00 over 5 installments (Nov 16, Dec 1 ... Mar 1) = 450.00
        _three_months(client, user_id)

        response = _compare(client, user_id, goal["id"])
        body = response.json()

        assert response.status_code == 200, response.text
        assert body["goal_id"] == goal["id"]
        assert body["as_of"] == "2026-11-16"
        assert (body["goal_currency"], body["base_currency"]) == ("EUR", "EUR")
        assert body["status"] == "comparable"
        assert body["analysis_period_start"] == "2026-08-01"
        assert body["analysis_period_end"] == "2026-10-31"
        assert body["months_used"] == 3
        assert body["average_monthly_income"] == "3000.00"
        assert body["average_monthly_expenses"] == "2400.00"
        assert body["average_monthly_net_flow"] == "600.00"
        assert body["required_per_installment"] == "450.00"
        assert body["historical_difference"] == "150.00"
        assert body["difference_direction"] == "surplus"
        assert body["limitations"] == ["budgets_not_modelled", "goal_commitments_not_modelled"]
        assert [m["period_start"] for m in body["months"]] == ["2026-08-01", "2026-09-01", "2026-10-01"]
        assert [m["net_flow"] for m in body["months"]] == ["600.00", "600.00", "600.00"]
        assert all(m["has_activity"] and m["included_in_average"] for m in body["months"])

    def test_the_required_installment_is_the_goal_plan_s_own(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, target="1000.00", target_date="2027-01-31")  # 3 installments -> 333.34 (rounded up)
        _three_months(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=100)  # tracked progress lowers the remainder

        plan = client.post(f"/api/v1/goals/{goal['id']}/plan", headers=auth_headers(user_id), json={}).json()
        body = _compare(client, user_id, goal["id"]).json()

        assert body["required_per_installment"] == plan["required_per_installment"] == "300.00"
        assert body["historical_difference"] == "300.00"

    def test_negative_and_zero_net_flow(self, client: TestClient, clean_database: None) -> None:
        deficit_user, zero_user = str(uuid4()), str(uuid4())
        deficit_goal, zero_goal = _goal(client, deficit_user), _goal(client, zero_user)
        _three_months(client, deficit_user, income="2000.00", expense="2300.00")
        _three_months(client, zero_user, income="2000.00", expense="2000.00")

        deficit = _compare(client, deficit_user, deficit_goal["id"]).json()
        zero = _compare(client, zero_user, zero_goal["id"]).json()

        assert (deficit["average_monthly_net_flow"], deficit["historical_difference"], deficit["difference_direction"]) == ("-300.00", "-750.00", "shortfall")
        assert (zero["average_monthly_net_flow"], zero["historical_difference"], zero["difference_direction"]) == ("0.00", "-450.00", "shortfall")


class TestCompletedMonthBoundaries:
    def test_only_the_three_completed_months_count(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        _three_months(client, user_id)
        # Just outside the window on both sides, and the in-progress month, all large:
        for outside in ("2026-07-31", "2026-11-01", "2026-11-16"):
            _income(client, user_id, "50000.00", outside)
            _expense(client, user_id, "40000.00", outside)
        # Just inside on both ends (first day of August, last day of October):
        _income(client, user_id, "300.00", "2026-08-01")
        _expense(client, user_id, "300.00", "2026-10-31")

        body = _compare(client, user_id, goal["id"]).json()

        assert [m["income_total"] for m in body["months"]] == ["3300.00", "3000.00", "3000.00"]
        assert [m["expense_total"] for m in body["months"]] == ["2400.00", "2400.00", "2700.00"]
        assert [m["net_flow"] for m in body["months"]] == ["900.00", "600.00", "300.00"]
        assert body["average_monthly_net_flow"] == "600.00"  # (900 + 600 + 300) / 3; the large records outside the window are excluded

    def test_the_window_follows_the_calendar_across_a_year_end(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        class JanuaryDate(date):
            @classmethod
            def today(cls) -> "JanuaryDate":
                return cls(2027, 1, 10)

        monkeypatch.setattr(goal_service, "date", JanuaryDate)
        user_id = str(uuid4())
        goal = _goal(client, user_id, target_date="2027-06-30")

        body = _compare(client, user_id, goal["id"]).json()

        assert (body["analysis_period_start"], body["analysis_period_end"]) == ("2026-10-01", "2026-12-31")
        assert [m["period_start"] for m in body["months"]] == ["2026-10-01", "2026-11-01", "2026-12-01"]

    def test_the_first_of_the_month_is_in_progress_not_complete(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        class FirstDate(date):
            @classmethod
            def today(cls) -> "FirstDate":
                return cls(2026, 11, 1)

        monkeypatch.setattr(goal_service, "date", FirstDate)
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        body = _compare(client, user_id, goal["id"]).json()

        assert body["analysis_period_end"] == "2026-10-31"


class TestMissingOrUnusableHistory:
    def test_a_new_user_gets_insufficient_data_not_zero_obligations(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)

        body = _compare(client, user_id, goal["id"]).json()

        assert body["status"] == "insufficient_data"
        assert body["limitations"] == ["fewer_than_two_active_months", "budgets_not_modelled", "goal_commitments_not_modelled"]
        assert (body["average_monthly_income"], body["average_monthly_net_flow"], body["historical_difference"]) == (None, None, None)
        assert body["months_used"] == 0
        assert len(body["months"]) == 3
        assert body["required_per_installment"] == "450.00"

    def test_a_single_active_month_is_insufficient_but_still_described(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        _income(client, user_id, "3000.00", "2026-10-15")
        _expense(client, user_id, "2400.00", "2026-10-15")

        body = _compare(client, user_id, goal["id"]).json()

        assert body["status"] == "insufficient_data"
        assert body["average_monthly_net_flow"] is None
        assert body["months"][2]["net_flow"] == "600.00"
        assert [m["has_activity"] for m in body["months"]] == [False, False, True]

    def test_a_month_without_records_is_left_out_not_counted_as_zero(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        for month in ("2026-09-15", "2026-10-15"):
            _income(client, user_id, "3000.00", month)
            _expense(client, user_id, "2400.00", month)

        body = _compare(client, user_id, goal["id"]).json()

        assert body["status"] == "comparable"
        assert body["months_used"] == 2
        assert body["average_monthly_net_flow"] == "600.00"  # not 400.00
        assert "months_without_activity_excluded" in body["limitations"]
        assert [m["included_in_average"] for m in body["months"]] == [False, True, True]

    def test_an_unresolved_record_blocks_the_average(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        _three_months(client, user_id)
        # A legacy Expense with no base-currency amount (the API always resolves FX).
        with SessionLocal() as session:
            session.add(ExpenseModel(
                user_id=user_id, category_id=None, title="Legacy USD", amount=Decimal("999.00"),
                currency="USD", expense_date=date(2026, 9, 20), source="manual",
            ))
            session.commit()

        body = _compare(client, user_id, goal["id"]).json()

        assert body["status"] == "insufficient_data"
        assert "unresolved_currency_data" in body["limitations"]
        assert (body["average_monthly_net_flow"], body["historical_difference"]) == (None, None)
        assert body["months"][1]["unresolved_expense_count"] == 1
        assert body["months"][1]["expense_total"] == "2400.00"  # the unresolved 999.00 is not in the total


class TestGoalCurrencyAndRequirement:
    def test_a_goal_in_another_currency_than_the_base_is_not_compared(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id, currency="USD")
        _three_months(client, user_id)

        body = _compare(client, user_id, goal["id"]).json()

        assert body["status"] == "currency_mismatch"
        assert (body["goal_currency"], body["base_currency"]) == ("USD", "EUR")
        assert body["historical_difference"] is None and body["difference_direction"] is None
        assert body["average_monthly_net_flow"] == "600.00"  # described in the base currency, not converted
        assert body["required_per_installment"] == "450.00"

    def test_goals_without_a_required_installment(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        no_date = _goal(client, user_id, target_date=None)
        passed = _goal(client, user_id, target_date="2026-11-15")
        funded = _goal(client, user_id, target="100.00")
        create_goal_transaction(client, user_id, funded["id"], amount=100)
        archived = _goal(client, user_id)
        assert client.patch(f"/api/v1/goals/{archived['id']}", headers=auth_headers(user_id), json={"status": "archived"}).status_code == 200
        _three_months(client, user_id)

        for goal in (no_date, passed, funded, archived):
            body = _compare(client, user_id, goal["id"]).json()

            assert body["status"] == "no_required_installment", goal["id"]
            assert body["required_per_installment"] is None
            assert body["historical_difference"] is None
            assert body["average_monthly_net_flow"] == "600.00"


class TestNoDoubleCounting:
    def test_balances_transfers_adjustments_and_goal_money_are_not_income_or_expenses(self, client: TestClient, clean_database: None) -> None:
        clean_user, busy_user = str(uuid4()), str(uuid4())
        clean_goal, busy_goal = _goal(client, clean_user), _goal(client, busy_user)
        _three_months(client, clean_user)
        _three_months(client, busy_user)

        # Everything that moves money but is NOT income or an expense:
        main = create_account(client, busy_user, name="Main", opening_balance="5000.00", opening_balance_date=OPENING_BALANCE_DATE)
        savings = create_account(client, busy_user, name="Savings")
        create_account_transaction(client, busy_user, main["id"], amount="700.00", direction="credit", transaction_date="2026-09-10")
        create_account_transaction(client, busy_user, main["id"], amount="200.00", direction="debit", transaction_date="2026-10-10")
        create_account_transfer(client, busy_user, main["id"], savings["id"], amount="1000.00", transfer_date="2026-09-20")
        create_goal_transaction(client, busy_user, busy_goal["id"], amount=300)  # tracked
        linked = client.post(
            f"/api/v1/goals/{busy_goal['id']}/transactions",
            headers=auth_headers(busy_user),
            json={"type": "contribution", "amount": "400.00", "account_id": main["id"], "client_request_id": str(uuid4())},
        )
        assert linked.status_code == 201, linked.text

        clean = _compare(client, clean_user, clean_goal["id"]).json()
        busy = _compare(client, busy_user, busy_goal["id"]).json()

        for field in ("average_monthly_income", "average_monthly_expenses", "average_monthly_net_flow", "months", "months_used"):
            assert busy[field] == clean[field], field

    def test_an_account_linked_income_and_expense_is_counted_once(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        account = create_account(client, user_id, name="Main", opening_balance="1000.00", opening_balance_date=OPENING_BALANCE_DATE)
        for month in ("2026-08-15", "2026-09-15", "2026-10-15"):
            _income(client, user_id, "3000.00", month, account_id=account["id"])
            _expense(client, user_id, "2400.00", month, account_id=account["id"])

        body = _compare(client, user_id, goal["id"]).json()

        assert [m["income_total"] for m in body["months"]] == ["3000.00"] * 3
        assert [m["expense_total"] for m in body["months"]] == ["2400.00"] * 3
        assert [(m["income_count"], m["expense_count"]) for m in body["months"]] == [(1, 1)] * 3


class TestAuthenticationAndOwnership:
    def test_requires_authentication(self, client: TestClient, clean_database: None) -> None:
        goal = _goal(client, str(uuid4()))

        assert client.get(f"/api/v1/goals/{goal['id']}/plan/history-comparison").status_code == 401

    def test_another_users_goal_looks_exactly_like_a_missing_goal(self, client: TestClient, clean_database: None) -> None:
        owner, intruder = str(uuid4()), str(uuid4())
        goal = _goal(client, owner)
        _three_months(client, owner)

        foreign = _compare(client, intruder, goal["id"])
        missing = _compare(client, intruder, str(uuid4()))

        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert "3000" not in foreign.text and goal["name"] not in foreign.text

    def test_a_malformed_goal_id_is_a_validation_error(self, client: TestClient, clean_database: None) -> None:
        assert client.get("/api/v1/goals/not-a-uuid/plan/history-comparison", headers=auth_headers(str(uuid4()))).status_code == 422

    def test_another_users_records_never_enter_the_history(self, client: TestClient, clean_database: None) -> None:
        mine, other = str(uuid4()), str(uuid4())
        goal = _goal(client, mine)
        _three_months(client, mine)
        _three_months(client, other, income="9000.00", expense="100.00")

        body = _compare(client, mine, goal["id"]).json()

        assert body["average_monthly_net_flow"] == "600.00"


class TestReadOnly:
    def test_a_new_user_s_request_executes_no_write_and_creates_no_settings_row(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        # Creating a Goal must not have bootstrapped settings, or this test proves nothing.
        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user_id}).scalar_one() == 0

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = _compare(client, user_id, goal["id"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200, response.text
        assert response.json()["base_currency"] == "EUR"
        assert statements, "the request must have read the database"
        for statement in statements:
            assert statement.startswith("SELECT"), statement
            assert "FOR UPDATE" not in statement and "FOR SHARE" not in statement, statement

        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user_id}).scalar_one() == 0

    def test_the_stored_data_is_identical_before_and_after(self, client: TestClient, clean_database: None) -> None:
        user_id = str(uuid4())
        goal = _goal(client, user_id)
        _three_months(client, user_id)
        create_goal_transaction(client, user_id, goal["id"], amount=100)

        def snapshot() -> list[Any]:
            with SessionLocal() as session:
                return [
                    session.execute(text("SELECT id::text, updated_at::text, priority_rank FROM goals ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, type FROM goal_transactions ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, base_amount::text FROM income ORDER BY id")).all(),
                    session.execute(text("SELECT id::text, amount::text, base_amount::text FROM expenses ORDER BY id")).all(),
                    session.execute(text("SELECT count(*) FROM account_transactions")).scalar_one(),
                    session.execute(text("SELECT count(*) FROM rule_executions")).scalar_one(),
                    session.execute(text("SELECT count(*) FROM user_financial_settings")).scalar_one(),
                ]

        before = snapshot()

        for _ in range(2):
            assert _compare(client, user_id, goal["id"]).status_code == 200

        assert snapshot() == before
