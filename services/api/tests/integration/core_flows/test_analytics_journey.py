"""Dashboard and Analytics journey across modules (VF-MVP-CORE-006).

The analytics router tests cover each endpoint on its own. This file builds ONE realistic dataset
(Accounts, linked and unlinked Income and Expenses, a posted and a planned Transfer, a Goal reservation,
a Budget, a confirmed Receipt, a foreign-currency record with a persisted FX snapshot and controlled
unresolved legacy rows) and reconciles every analytics endpoint against independent SQL.

"Today" is frozen on the analytics router only (FROZEN_TODAY), so every figure holds on any calendar day.

Invariants asserted here:
- Income/Expense totals and counts equal SQL over RESOLVED base-currency snapshots only; unresolved rows
  (no snapshot, or a snapshot in another base currency) are counted separately, never as zero, never mixed in;
- Net = Income - Expenses and is not an Account balance; savings rate is null exactly when Income is zero;
- Transfers (posted or planned), Goal reservations and tracked contributions, and Account opening balances
  change no Income, Expense, Net, trend, forecast or Budget figure;
- a confirmed Receipt adds exactly one Expense to every view, and a refused repeat adds nothing;
- the endpoints agree with each other (trend buckets = overview, category summary = monthly summary,
  category trend = spending trend) and recalculate after an edit or delete;
- another user's data never appears; historical FX snapshots are never recomputed.
"""
import io
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.analytics import analytics_router
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.fx import fx_service
from app.modules.fx.fx_schemas import FxRateResult
from app.modules.income.income_models import IncomeModel
from app.modules.receipts import receipt_ocr_service, receipt_storage_service
from tests.helpers import auth_headers

FROZEN_TODAY = date(2026, 10, 15)
Q = Decimal("0.01")


def _freeze(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    class Frozen(date):
        @classmethod
        def today(cls) -> date:
            return today

    monkeypatch.setattr(analytics_router, "date", Frozen)


# 1 USD = 0.9 EUR unless a test changes it; identity for the same currency. No provider is reached.
FX = {"USD": Decimal("0.9")}


def _fx(original_currency: str, base_currency: str, transaction_date: date, as_of: date) -> FxRateResult:
    if original_currency == base_currency:
        return FxRateResult(rate=Decimal("1"), actual_rate_date=transaction_date, source="identity")
    return FxRateResult(rate=FX[original_currency], actual_rate_date=transaction_date, source="ecb")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    FX["USD"] = Decimal("0.9")
    monkeypatch.setattr(fx_service, "resolve_fx_rate", _fx)
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", str(tmp_path / "uploads"))
    _freeze(monkeypatch, FROZEN_TODAY)


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).scalar()


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


# ---- independent SQL (resolved = a snapshot in the user's base currency, EUR) -------------------------------


def sql_flow(user: str, table: str, date_column: str, start: date, end: date) -> Dict[str, Any]:
    where = f"user_id = :u and {date_column} between :s and :e"
    resolved = f"{where} and base_amount is not null and base_currency = 'EUR'"
    return {
        "total": _dec(_sql(f"select coalesce(sum(base_amount), 0) from {table} where {resolved}", u=user, s=start, e=end)),
        "count": _sql(f"select count(*) from {table} where {resolved}", u=user, s=start, e=end),
        "unresolved": _sql(
            f"select count(*) from {table} where {where} and (base_amount is null or base_currency <> 'EUR')",
            u=user, s=start, e=end,
        ),
    }


def month_bounds(year: int, month: int) -> tuple:
    start = date(year, month, 1)
    end = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def expected_overview(user: str, year: int, month: int, today: date = FROZEN_TODAY) -> Dict[str, Any]:
    start, end = month_bounds(year, month)
    if start > today:
        return {"income_total": "0.00", "expense_total": "0.00", "net_flow": "0.00", "savings": None,
                "income_count": 0, "expense_count": 0, "ui": 0, "ue": 0, "state": "future"}
    effective_end = min(end, today)
    income = sql_flow(user, "income", "received_at", start, effective_end)
    expense = sql_flow(user, "expenses", "expense_date", start, effective_end)
    net = income["total"] - expense["total"]
    savings = None if income["total"] == 0 else (net * 100 / income["total"]).quantize(Q, rounding=ROUND_HALF_EVEN)
    return {
        "income_total": str(income["total"].quantize(Q)), "expense_total": str(expense["total"].quantize(Q)),
        "net_flow": str(net.quantize(Q)), "savings": None if savings is None else str(savings),
        "income_count": income["count"], "expense_count": expense["count"],
        "ui": income["unresolved"], "ue": expense["unresolved"],
        "state": "complete" if end < today else "in_progress",
    }


class Api:
    def __init__(self, client: TestClient, user: Optional[str] = None) -> None:
        self.client = client
        self.user = user or str(uuid4())
        self.headers = auth_headers(self.user)

    def call(self, method: str, path: str, expect: Optional[int] = None, **kwargs: Any) -> Any:
        response = self.client.request(method, path, headers=self.headers, **kwargs)
        if expect is not None:
            assert response.status_code == expect, f"{method} {path} -> {response.status_code} {response.text}"
        return response

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, 200, params=params).json()

    def account(self, name: str, opening: str = "0.00") -> str:
        body = {"name": name, "type": "checking", "currency": "EUR", "opening_balance": opening, "opening_balance_date": "2026-08-01"}
        return self.call("POST", "/api/v1/accounts", 201, json=body).json()["id"]

    def category(self, name: str) -> str:
        return self.call("POST", "/api/v1/categories", 201, json={"name": name, "color": "#FF5733", "icon": "x"}).json()["id"]

    def income(self, amount: str, on: str, currency: str = "EUR", source: str = "salary", account: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"amount": amount, "currency": currency, "received_at": on, "source": source}
        if account:
            body["account_id"] = account
        return self.call("POST", "/api/v1/income", 201, json=body).json()

    def expense(self, amount: str, on: str, currency: str = "EUR", category: Optional[str] = None, account: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"title": "e", "amount": amount, "currency": currency, "expense_date": on, "client_request_id": str(uuid4())}
        if category:
            body["category_id"] = category
        if account:
            body["account_id"] = account
        return self.call("POST", "/api/v1/expenses", 201, json=body).json()

    def overview(self, year: int, month: int) -> Dict[str, Any]:
        return self.get("/api/v1/analytics/financial-overview", year=year, month=month)

    def balance(self, account_id: str) -> Decimal:
        accounts = self.call("GET", "/api/v1/accounts", 200).json()
        return _dec(next(a["current_balance"] for a in accounts if a["id"] == account_id))


def legacy_expense(user: str, on: date, amount: str = "999.00", base_currency: Optional[str] = None, base_amount: Optional[str] = None) -> None:
    """A row without a usable snapshot: no base_amount (pre-FX data) or a snapshot in ANOTHER base currency."""
    snapshot: Dict[str, Any] = {}
    if base_currency is not None:  # the database requires a snapshot to be all-or-none
        snapshot = dict(base_currency=base_currency, base_amount=Decimal(base_amount), fx_rate=Decimal("0.5"),
                        fx_rate_date=on, fx_source="ecb")
    with SessionLocal() as session:
        session.add(ExpenseModel(user_id=user, title="legacy", amount=Decimal(amount), currency="USD", expense_date=on,
                                 source="manual", **snapshot))
        session.commit()


def legacy_income(user: str, on: date, amount: str = "888.00") -> None:
    with SessionLocal() as session:
        session.add(IncomeModel(user_id=user, amount=Decimal(amount), currency="USD", received_at=on, source="salary"))
        session.commit()


def resolved_expense(user: str, on: date, amount: str) -> None:
    """A fully resolved EUR Expense inserted directly, so calendar tests can use dates the real clock forbids."""
    with SessionLocal() as session:
        session.add(ExpenseModel(user_id=user, title="e", amount=Decimal(amount), currency="EUR", expense_date=on, source="manual",
                                 base_currency="EUR", base_amount=Decimal(amount), fx_rate=Decimal("1"), fx_rate_date=on, fx_source="identity"))
        session.commit()


def resolved_income(user: str, on: date, amount: str) -> None:
    with SessionLocal() as session:
        session.add(IncomeModel(user_id=user, amount=Decimal(amount), currency="EUR", received_at=on, source="salary",
                                base_currency="EUR", base_amount=Decimal(amount), fx_rate=Decimal("1"), fx_rate_date=on, fx_source="identity"))
        session.commit()


class Dataset:
    """The journey's records. Dates: Aug (complete, empty), Sep (complete), Oct (in progress, today = Oct 15)."""

    def build(self, client: TestClient) -> "Dataset":
        a = self.api = Api(client)
        self.checking = a.account("Checking", "1000.00")
        self.savings = a.account("Savings", "200.00")
        self.food = a.category("Journey Food")
        self.rent = a.category("Journey Rent")
        # September (complete)
        a.income("3000.00", "2026-09-25", account=self.checking)
        a.expense("120.00", "2026-09-10", category=self.food, account=self.checking)
        a.expense("800.00", "2026-09-20", category=self.rent)
        # October (in progress up to the 15th)
        a.income("500.00", "2026-10-01", source="freelance")
        a.income("200.00", "2026-10-05", currency="USD")  # 180.00 EUR snapshot
        a.income("20.00", "2026-10-06", source="refund")  # income, never subtracted from Expenses
        self.food_expense = a.expense("45.50", "2026-10-02", category=self.food, account=self.checking)
        self.usd_expense = a.expense("100.00", "2026-10-03", currency="USD", category=self.food)  # 90.00 EUR snapshot
        a.expense("10.00", "2026-10-14")  # uncategorized
        # After "today" (kept out of Overview, trends, forecast and Budget; inside monthly-summary by contract)
        self.future_income = a.income("777.00", "2026-10-20")
        self.future_expense = a.expense("33.00", "2026-10-20", category=self.food)
        # Controlled unresolved fixtures: no snapshot at all, and a snapshot in another base currency
        legacy_expense(a.user, date(2026, 10, 4))
        legacy_expense(a.user, date(2026, 9, 12), base_currency="GBP", base_amount="50.00")
        legacy_income(a.user, date(2026, 10, 7))
        self.budget = a.call("POST", "/api/v1/budgets", 201, json={
            "name": "Food Oct", "limit_amount": "200.00", "period": "monthly", "start_date": "2026-10-01", "category_id": self.food,
        }).json()
        return self

    def add_non_expense_money_movement(self) -> None:
        """Everything that moves money or intent WITHOUT being an Income or an Expense."""
        a = self.api
        a.call("POST", "/api/v1/account-transfers", 201, json={
            "client_request_id": str(uuid4()), "source_account_id": self.checking, "destination_account_id": self.savings,
            "amount": "100.00", "transfer_date": "2026-10-03"})  # posted
        a.call("POST", "/api/v1/account-transfers", 201, json={
            "client_request_id": str(uuid4()), "source_account_id": self.savings, "destination_account_id": self.checking,
            "amount": "50.00", "transfer_date": "2027-03-01"})  # planned (future)
        goal = a.call("POST", "/api/v1/goals", 201, json={
            "name": "Holiday", "target_amount": "2000.00", "currency": "EUR", "target_date": "2027-12-31", "status": "active"}).json()
        self.goal = goal["id"]
        a.call("POST", f"/api/v1/goals/{goal['id']}/transactions", 201, json={
            "type": "contribution", "amount": "60.00", "account_id": self.checking, "client_request_id": str(uuid4())})  # reservation
        a.call("POST", f"/api/v1/goals/{goal['id']}/transactions", 201, json={"type": "contribution", "amount": "30.00"})  # tracked
        a.call("POST", f"/api/v1/goals/{goal['id']}/transactions", 201, json={"type": "withdrawal", "amount": "10.00"})  # tracked
        a.call("POST", f"/api/v1/accounts/{self.savings}/transactions", 201, json={
            "direction": "credit", "amount": "5.00", "transaction_date": "2026-10-04"})  # manual adjustment

    def confirm_receipt(self, monkeypatch: pytest.MonkeyPatch, amount: str = "12.34", on: str = "2026-10-07") -> str:
        class Ocr:
            def extract_text(self, file_path: Path) -> str:
                return f"SHOP\n07.10.2026\nSUMME {amount.replace('.', ',')} EUR"

        monkeypatch.setattr(receipt_ocr_service, "receipt_ocr_provider", Ocr())
        a = self.api
        buffer = io.BytesIO()
        Image.new("RGB", (40, 40), "white").save(buffer, "PNG")
        receipt = a.call("POST", "/api/v1/receipts/upload", 201, files={"file": ("r.png", buffer.getvalue(), "image/png")}).json()
        a.call("POST", f"/api/v1/receipts/{receipt['id']}/process", 200)
        confirmed = a.call("POST", f"/api/v1/receipts/{receipt['id']}/confirm", 200, json={
            "category_id": self.food, "account_id": self.savings, "expense_date": on}).json()
        self.receipt = receipt["id"]
        return confirmed["expense"]["id"]


def views(api: Api) -> Dict[str, Any]:
    """Every analytics read the Dashboard and Analytics screens make, for the frozen month."""
    return {
        "overview_oct": api.overview(2026, 10),
        "overview_sep": api.overview(2026, 9),
        "income_expense_trend": api.get("/api/v1/analytics/income-expense-trend", count=3),
        "monthly_summary": api.get("/api/v1/analytics/monthly-summary", year=2026, month=10),
        "category_summary": api.get("/api/v1/analytics/category-summary", year=2026, month=10),
        "spending_trend": api.get("/api/v1/analytics/spending-trend", period="month", count=3),
        "category_trend": api.get("/api/v1/analytics/category-trend", period="month", count=3),
        "forecast": api.get("/api/v1/analytics/spending-forecast"),
        "budget_status": api.get("/api/v1/analytics/budget-status"),
    }


# ---------------------------------------------------------------------------------------------
# Part A - Financial Overview against SQL
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("year,month", [(2026, 10), (2026, 9), (2026, 8), (2026, 11), (2027, 2)])
def test_financial_overview_equals_independent_sql_for_every_period_state(
    client: TestClient, clean_database: None, year: int, month: int,
) -> None:
    data = Dataset().build(client)

    body = data.api.overview(year, month)
    expected = expected_overview(data.api.user, year, month)

    assert body["income_total"] == expected["income_total"] and body["expense_total"] == expected["expense_total"]
    assert body["net_flow"] == expected["net_flow"] and body["savings_rate_percent"] == expected["savings"]
    assert (body["income_count"], body["expense_count"]) == (expected["income_count"], expected["expense_count"])
    assert (body["unresolved_income_count"], body["unresolved_expense_count"]) == (expected["ui"], expected["ue"])
    assert body["period_state"] == expected["state"]
    assert _dec(body["net_flow"]) == _dec(body["income_total"]) - _dec(body["expense_total"])


def test_the_october_figures_are_what_the_dataset_says_and_flag_the_unresolved_rows(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)

    october = data.api.overview(2026, 10)
    september = data.api.overview(2026, 9)

    # Income: 500 + 180 (USD snapshot) + 20 refund = 700; the legacy 888 USD row is unresolved; Oct 20 is after "today".
    assert (october["income_total"], october["income_count"], october["unresolved_income_count"]) == ("700.00", 3, 1)
    # Expenses: 45.50 + 90.00 (USD snapshot) + 10.00 = 145.50; the legacy row is unresolved; Oct 20 excluded.
    assert (october["expense_total"], october["expense_count"], october["unresolved_expense_count"]) == ("145.50", 3, 1)
    assert october["net_flow"] == "554.50" and october["savings_rate_percent"] == "79.21"
    assert october["period_state"] == "in_progress" and october["effective_end"] == "2026-10-15"
    assert october["data_status"] == "incomplete_data"
    # September: the GBP-snapshot row is a snapshot in ANOTHER base currency: unresolved, never mixed into the total.
    assert (september["income_total"], september["expense_total"], september["net_flow"]) == ("3000.00", "920.00", "2080.00")
    assert (september["expense_count"], september["unresolved_expense_count"]) == (2, 1)
    assert september["data_status"] == "incomplete_data" and september["period_state"] == "complete"


def test_an_empty_or_zero_income_period_is_valid_and_has_no_fabricated_savings_rate(client: TestClient, clean_database: None) -> None:
    api = Api(client)
    api.expense("40.00", "2026-10-02")

    empty = api.overview(2026, 8)
    expenses_only = api.overview(2026, 10)

    assert (empty["income_total"], empty["expense_total"], empty["net_flow"], empty["savings_rate_percent"]) == ("0.00", "0.00", "0.00", None)
    assert empty["data_status"] == "complete_data" and empty["period_state"] == "complete"
    assert (expenses_only["net_flow"], expenses_only["savings_rate_percent"]) == ("-40.00", None)


@pytest.mark.parametrize(
    "today,year,month,state,effective_end",
    [
        (date(2028, 2, 29), 2028, 2, "in_progress", "2028-02-29"),  # leap day is the last day: still in progress
        (date(2028, 3, 1), 2028, 2, "complete", None),
        (date(2027, 3, 1), 2027, 2, "complete", None),
        (date(2027, 1, 1), 2026, 12, "complete", None),  # year transition
        (date(2026, 12, 31), 2026, 12, "in_progress", "2026-12-31"),
        (date(2026, 12, 31), 2027, 1, "future", None),
    ],
)
def test_month_boundaries_leap_years_and_year_transitions(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
    today: date, year: int, month: int, state: str, effective_end: Optional[str],
) -> None:
    _freeze(monkeypatch, today)
    api = Api(client)
    # Records on the first day, last day and the days just outside of the requested month.
    start, end = month_bounds(year, month)
    for day in (start - timedelta(days=1), start, end, end + timedelta(days=1)):
        resolved_income(api.user, day, "10.00")
        resolved_expense(api.user, day, "4.00")

    body = api.overview(year, month)

    assert body["period_state"] == state
    assert (body["period_start"], body["period_end"]) == (start.isoformat(), end.isoformat())
    if state == "complete":
        assert body["effective_end"] == end.isoformat()
    elif state == "future":
        assert body["effective_end"] is None and body["income_total"] == "0.00"
    else:
        assert body["effective_end"] == effective_end
    expected = expected_overview(api.user, year, month, today)
    assert (body["income_total"], body["expense_total"]) == (expected["income_total"], expected["expense_total"])


# ---------------------------------------------------------------------------------------------
# Part B - money flow invariants
# ---------------------------------------------------------------------------------------------


def test_transfers_goals_and_adjustments_change_no_income_expense_net_trend_forecast_or_budget(
    client: TestClient, clean_database: None,
) -> None:
    data = Dataset().build(client)
    before = views(data.api)
    balances_before = (data.api.balance(data.checking), data.api.balance(data.savings))

    data.add_non_expense_money_movement()

    assert views(data.api) == before
    # ...but they DO move Account balances (a posted Transfer: -100/+100; a reservation moves none; the adjustment +5).
    assert data.api.balance(data.checking) == balances_before[0] - Decimal("100.00")
    assert data.api.balance(data.savings) == balances_before[1] + Decimal("100.00") + Decimal("5.00")
    # Goal progress (not spending) reflects the contributions: 60 reserved + 30 tracked - 10 withdrawn.
    progress = data.api.get("/api/v1/analytics/goal-progress")
    assert next(g for g in progress if g["goal_id"] == data.goal)["current_amount"] == "80.00"


def test_net_is_recorded_income_minus_expenses_and_is_not_an_account_balance(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    data.add_non_expense_money_movement()
    october = data.api.overview(2026, 10)

    balance_change = (data.api.balance(data.checking) - Decimal("1000.00")) + (data.api.balance(data.savings) - Decimal("200.00"))

    assert october["net_flow"] == "554.50"
    assert balance_change != _dec(october["net_flow"])
    # Opening balances are not Income: the 1,200.00 opened in August appears in no total.
    assert _dec(data.api.overview(2026, 8)["income_total"]) == 0


def test_income_and_expenses_change_net_and_only_linked_ones_change_an_account_balance(client: TestClient, clean_database: None) -> None:
    api = Api(client)
    account = api.account("A", "100.00")
    before = api.overview(2026, 10)

    api.income("50.00", "2026-10-02")  # unlinked
    after_unlinked = api.overview(2026, 10)
    api.income("25.00", "2026-10-03", account=account)  # linked
    api.expense("10.00", "2026-10-04")  # unlinked
    api.expense("5.00", "2026-10-05", account=account)  # linked

    final = api.overview(2026, 10)
    assert _dec(after_unlinked["net_flow"]) - _dec(before["net_flow"]) == Decimal("50.00")
    assert final["net_flow"] == "60.00" and api.balance(account) == Decimal("120.00")


def test_a_confirmed_receipt_counts_once_in_every_view_and_a_repeat_changes_nothing(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Dataset().build(client)
    before = views(data.api)

    expense_id = data.confirm_receipt(monkeypatch)
    after = views(data.api)

    assert _dec(after["overview_oct"]["expense_total"]) - _dec(before["overview_oct"]["expense_total"]) == Decimal("12.34")
    assert after["overview_oct"]["expense_count"] == before["overview_oct"]["expense_count"] + 1
    assert after["overview_oct"]["income_total"] == before["overview_oct"]["income_total"]
    food = next(i for i in after["budget_status"] if i["budget_id"] == data.budget["id"])
    food_before = next(i for i in before["budget_status"] if i["budget_id"] == data.budget["id"])
    assert _dec(food["spent"]) - _dec(food_before["spent"]) == Decimal("12.34")
    assert _dec(after["monthly_summary"]["total_spent"]) - _dec(before["monthly_summary"]["total_spent"]) == Decimal("12.34")
    assert _sql("select count(*) from expenses where id = :e and source = 'receipt'", e=expense_id) == 1

    again = data.api.call("POST", f"/api/v1/receipts/{data.receipt}/confirm", None, json={})
    assert again.status_code == 409
    assert views(data.api) == after


def test_budget_spending_and_general_expense_totals_follow_their_own_documented_rules(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    status = next(i for i in data.api.get("/api/v1/analytics/budget-status") if i["budget_id"] == data.budget["id"])

    # Budget: ORIGINAL-currency EUR expenses of its category in the window up to today: 45.50 only. The USD food
    # expense (90.00 EUR snapshot) is another currency; the Oct 20 one is in the future.
    assert status["spent"] == "45.50" and status["category_name"] == "Journey Food"
    # General totals: BASE-currency snapshots of every category: 145.50 (which DOES include the USD expense).
    assert data.api.overview(2026, 10)["expense_total"] == "145.50"
    # Both are internally consistent with SQL.
    assert _dec(_sql(
        "select coalesce(sum(amount),0) from expenses where user_id=:u and currency='EUR' and category_id=:c "
        "and expense_date between '2026-10-01' and '2026-10-15'", u=data.api.user, c=data.food)) == Decimal("45.50")


# ---------------------------------------------------------------------------------------------
# Part C/D - endpoints agree with each other and with SQL
# ---------------------------------------------------------------------------------------------


def test_trend_buckets_equal_the_overview_and_sql_for_the_same_months(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    trend = data.api.get("/api/v1/analytics/income-expense-trend", count=3)

    assert [b["period_start"] for b in trend["buckets"]] == ["2026-08-01", "2026-09-01", "2026-10-01"]
    for bucket in trend["buckets"]:
        year, month = int(bucket["period_start"][:4]), int(bucket["period_start"][5:7])
        overview = data.api.overview(year, month)
        for field in ("income_total", "expense_total", "net_flow", "savings_rate_percent", "income_count", "expense_count",
                      "unresolved_income_count", "unresolved_expense_count"):
            assert bucket[field] == overview[field], (bucket["period_start"], field)
        assert bucket["is_complete"] == (overview["period_state"] == "complete")
        assert bucket["effective_end"] == (overview["effective_end"] or overview["period_end"])


def test_summaries_and_trends_reconcile_with_each_other_and_keep_uncategorized_visible(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    v = views(data.api)

    # category-summary(Oct) adds up to monthly-summary(Oct): both count the whole calendar month by contract.
    assert sum(_dec(c["total_spent"]) for c in v["category_summary"]) == _dec(v["monthly_summary"]["total_spent"])
    assert sum(c["expenses_count"] for c in v["category_summary"]) == v["monthly_summary"]["expenses_count"]
    assert sum(c["unresolved_expenses_count"] for c in v["category_summary"]) == v["monthly_summary"]["unresolved_expenses_count"]
    names = {c["category_name"]: c for c in v["category_summary"]}
    assert names["Uncategorized"]["total_spent"] == "10.00" and names["Journey Food"]["total_spent"] == "168.50"
    # monthly-summary(Oct) = overview(Oct) + the Oct 20 expense (documented difference: whole month vs through today).
    assert _dec(v["monthly_summary"]["total_spent"]) == _dec(v["overview_oct"]["expense_total"]) + Decimal("33.00")

    # category trend per bucket adds up to the spending trend bucket; every requested bucket exists.
    for index, bucket in enumerate(v["spending_trend"]["buckets"]):
        assert sum(_dec(c["buckets"][index]["total_spent"]) for c in v["category_trend"]["categories"]) == _dec(bucket["total_spent"])
        assert sum(c["buckets"][index]["expenses_count"] for c in v["category_trend"]["categories"]) == bucket["expenses_count"]
    assert len(v["spending_trend"]["buckets"]) == 3
    assert [c["category_name"] for c in v["category_trend"]["categories"]] == sorted(
        (c["category_name"] for c in v["category_trend"]["categories"]), key=str.casefold)
    # spending trend = overview expenses for the same month, and SQL.
    for bucket, overview in zip(v["spending_trend"]["buckets"][1:], (v["overview_sep"], v["overview_oct"])):
        assert bucket["total_spent"] == overview["expense_total"] and bucket["expenses_count"] == overview["expense_count"]
    sep = sql_flow(data.api.user, "expenses", "expense_date", date(2026, 9, 1), date(2026, 9, 30))
    assert _dec(v["spending_trend"]["buckets"][1]["total_spent"]) == sep["total"]


def test_period_over_period_uses_the_two_most_recent_complete_periods(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)

    trend = data.api.get("/api/v1/analytics/spending-trend", period="month", count=3)
    comparison = trend["period_over_period"]

    # Complete buckets are Aug (0.00) and Sep (920.00): October is in progress and is never compared.
    assert (comparison["previous_period_start"], comparison["current_period_start"]) == ("2026-08-01", "2026-09-01")
    assert (comparison["previous_total_spent"], comparison["current_total_spent"]) == ("0.00", "920.00")
    assert comparison["percent_change"] is None and comparison["direction"] == "up"
    # With a non-zero previous period the percentage is exact and rounded to two decimals.
    data.api.expense("92.00", "2026-08-10")
    changed = data.api.get("/api/v1/analytics/spending-trend", period="month", count=3)["period_over_period"]
    assert (changed["previous_total_spent"], changed["percent_change"], changed["direction"]) == ("92.00", "900.00", "up")


@pytest.mark.parametrize("period,count,first_start,weekday", [("day", 7, "2026-10-09", None), ("week", 3, "2026-09-28", 0), ("month", 2, "2026-09-01", None)])
def test_trend_buckets_are_calendar_aligned_chronological_and_all_present(
    client: TestClient, clean_database: None, period: str, count: int, first_start: str, weekday: Optional[int],
) -> None:
    api = Api(client)
    api.expense("5.00", "2026-10-15")

    trend = api.get("/api/v1/analytics/spending-trend", period=period, count=count)

    starts = [b["period_start"] for b in trend["buckets"]]
    assert len(starts) == count and starts == sorted(starts) and starts[0] == first_start
    if weekday is not None:
        assert all(date.fromisoformat(s).weekday() == weekday for s in starts), "weeks start on Monday"
    last = trend["buckets"][-1]
    assert last["is_complete"] is False and last["effective_end"] == "2026-10-15"
    assert all(b["is_complete"] for b in trend["buckets"][:-1])
    assert last["total_spent"] == "5.00" and all(b["total_spent"] == "0.00" for b in trend["buckets"][:-1])


def test_historical_fx_snapshots_are_used_and_never_recomputed(client: TestClient, clean_database: None) -> None:
    api = Api(client)
    api.expense("100.00", "2026-09-10", currency="USD")  # snapshot 90.00 at 0.9
    FX["USD"] = Decimal("0.5")  # the "market" moves afterwards
    api.expense("100.00", "2026-10-02", currency="USD")  # snapshot 50.00 at 0.5

    assert api.overview(2026, 9)["expense_total"] == "90.00"
    assert api.overview(2026, 10)["expense_total"] == "50.00"
    FX["USD"] = Decimal("2.0")
    assert api.overview(2026, 9)["expense_total"] == "90.00", "reads make no FX call and never revalue history"
    assert _sql("select base_amount from expenses where user_id = :u and expense_date = '2026-09-10'", u=api.user) == Decimal("90.00")


@pytest.mark.parametrize("row", ["no_snapshot", "other_base_currency"])
def test_an_unusable_snapshot_is_unresolved_in_every_view_and_never_a_known_zero(client: TestClient, clean_database: None, row: str) -> None:
    api = Api(client)
    api.expense("20.00", "2026-10-02")
    if row == "no_snapshot":
        legacy_expense(api.user, date(2026, 10, 3))
    else:
        legacy_expense(api.user, date(2026, 10, 3), base_currency="GBP", base_amount="999.00")

    v = views(api)

    assert (v["overview_oct"]["expense_total"], v["overview_oct"]["expense_count"], v["overview_oct"]["unresolved_expense_count"]) == ("20.00", 1, 1)
    assert v["overview_oct"]["data_status"] == "incomplete_data"
    assert (v["monthly_summary"]["total_spent"], v["monthly_summary"]["expenses_count"], v["monthly_summary"]["unresolved_expenses_count"]) == ("20.00", 1, 1)
    assert v["spending_trend"]["buckets"][-1]["unresolved_expenses_count"] == 1
    assert v["income_expense_trend"]["buckets"][-1]["unresolved_expense_count"] == 1
    # The forecast refuses to project from known-incomplete data instead of inventing figures.
    assert v["forecast"]["forecast_status"] == "incomplete_data"
    assert v["forecast"]["average_daily_spending"] is None and v["forecast"]["projected_spending"] is None
    assert v["forecast"]["unresolved_expenses_count"] == 1 and v["forecast"]["spent_to_date"] == "20.00"


# ---------------------------------------------------------------------------------------------
# Part E - forecast definition
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "today,spent,days_elapsed,days_in_month,average,projected",
    [
        (date(2026, 10, 1), "31.00", 1, 31, "31.00", "961.00"),  # first day
        (date(2026, 10, 31), "310.00", 31, 31, "10.00", "310.00"),  # last day: projection = spent
        (date(2026, 10, 3), "100.00", 3, 31, "33.33", "1033.33"),  # projection uses the UNROUNDED daily average
        (date(2028, 2, 29), "58.00", 29, 29, "2.00", "58.00"),  # leap year
        (date(2027, 2, 28), "56.00", 28, 28, "2.00", "56.00"),  # non-leap February
        (date(2026, 10, 15), "0.00", 15, 31, "0.00", "0.00"),  # empty month is a valid zero projection
    ],
)
def test_forecast_is_the_linear_run_rate_with_exact_day_counts_and_rounding(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
    today: date, spent: str, days_elapsed: int, days_in_month: int, average: str, projected: str,
) -> None:
    _freeze(monkeypatch, today)
    api = Api(client)
    if Decimal(spent) > 0:
        resolved_expense(api.user, today, spent)

    forecast = api.get("/api/v1/analytics/spending-forecast")

    assert forecast["method"] == "linear_run_rate" and forecast["forecast_status"] == "available"
    assert (forecast["days_elapsed"], forecast["days_in_month"]) == (days_elapsed, days_in_month)
    assert (forecast["period_start"], forecast["period_end"], forecast["as_of"]) == (
        today.replace(day=1).isoformat(), month_bounds(today.year, today.month)[1].isoformat(), today.isoformat())
    assert forecast["spent_to_date"] == spent
    assert (forecast["average_daily_spending"], forecast["projected_spending"]) == (average, projected)


def test_the_forecast_and_the_budget_projection_keep_their_separate_definitions(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)

    forecast = data.api.get("/api/v1/analytics/spending-forecast")
    budget = next(i for i in data.api.get("/api/v1/analytics/budget-status") if i["budget_id"] == data.budget["id"])

    assert forecast["forecast_status"] == "incomplete_data"  # unresolved October rows exist: no projection at all
    # The Budget projection is per Budget (original currency, its category) and is computed independently.
    assert budget["spent"] == "45.50" and budget["projected_spending"] is not None
    assert _dec(budget["projected_spending"]) == (Decimal("45.50") / budget["days_elapsed"] * budget["days_in_period"]).quantize(Q)


# ---------------------------------------------------------------------------------------------
# Edits, deletes, isolation, validation
# ---------------------------------------------------------------------------------------------


def test_editing_and_deleting_records_recalculates_every_view_without_stale_totals(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    a = data.api
    before = views(a)

    a.call("PATCH", f"/api/v1/expenses/{data.food_expense['id']}", 200, json={"amount": "55.50"})
    edited = views(a)
    assert _dec(edited["overview_oct"]["expense_total"]) - _dec(before["overview_oct"]["expense_total"]) == Decimal("10.00")
    assert edited["overview_oct"] == {**before["overview_oct"], "expense_total": "155.50", "net_flow": "544.50", "savings_rate_percent": "77.79"}
    assert next(i for i in edited["budget_status"] if i["budget_id"] == data.budget["id"])["spent"] == "55.50"

    a.call("DELETE", f"/api/v1/expenses/{data.food_expense['id']}", 204)
    deleted = views(a)
    assert deleted["overview_oct"]["expense_total"] == "100.00" and deleted["overview_oct"]["expense_count"] == 2
    expected = expected_overview(a.user, 2026, 10)
    assert (deleted["overview_oct"]["expense_total"], deleted["overview_oct"]["net_flow"]) == (expected["expense_total"], expected["net_flow"])
    assert next(i for i in deleted["budget_status"] if i["budget_id"] == data.budget["id"])["spent"] == "0.00"

    income_id = _sql("select id from income where user_id = :u and amount = 500.00", u=a.user)
    a.call("DELETE", f"/api/v1/income/{income_id}", 204)
    after_income = a.overview(2026, 10)
    assert after_income["income_total"] == "200.00" and after_income["income_count"] == 2
    assert after_income["income_total"] == expected_overview(a.user, 2026, 10)["income_total"]


def test_every_analytics_endpoint_is_scoped_to_its_user(client: TestClient, clean_database: None) -> None:
    data = Dataset().build(client)
    data.add_non_expense_money_movement()
    stranger = Api(client)

    v = views(stranger)

    for key in ("overview_oct", "overview_sep"):
        assert (v[key]["income_total"], v[key]["expense_total"], v[key]["income_count"], v[key]["unresolved_expense_count"]) == ("0.00", "0.00", 0, 0)
    assert v["monthly_summary"]["total_spent"] == "0.00" and v["category_summary"] == []
    assert all(b["total_spent"] == "0.00" for b in v["spending_trend"]["buckets"])
    assert v["category_trend"]["categories"] == [] and v["budget_status"] == []
    assert v["forecast"]["spent_to_date"] == "0.00" and v["forecast"]["unresolved_expenses_count"] == 0
    assert stranger.get("/api/v1/analytics/goal-progress") == []
    assert stranger.call("GET", "/api/v1/analytics/category-trend", 404, params={"period": "month", "category_id": data.food}).status_code == 404


@pytest.mark.parametrize(
    "path,params,status",
    [
        ("financial-overview", {"year": 1999, "month": 1}, 422),
        ("financial-overview", {"year": 2026, "month": 13}, 422),
        ("financial-overview", {"year": 2026}, 422),
        ("monthly-summary", {"year": 2026, "month": 0}, 422),
        ("category-summary", {"year": 2026}, 422),
        ("category-summary", {"month": 5}, 422),
        ("spending-trend", {}, 422),
        ("spending-trend", {"period": "year"}, 422),
        ("spending-trend", {"period": "day", "count": 0}, 422),
        ("spending-trend", {"period": "day", "count": 367}, 422),
        ("spending-trend", {"period": "week", "count": 105}, 422),
        ("spending-trend", {"period": "month", "count": 25}, 422),
        ("category-trend", {"period": "month", "category_id": "not-a-uuid"}, 422),
        ("income-expense-trend", {"count": 0}, 422),
        ("income-expense-trend", {"count": 25}, 422),
    ],
)
def test_invalid_analytics_parameters_are_refused(client: TestClient, clean_database: None, path: str, params: dict, status: int) -> None:
    assert Api(client).call("GET", f"/api/v1/analytics/{path}", None, params=params).status_code == status


def test_documented_defaults_and_maximums_are_applied(client: TestClient, clean_database: None) -> None:
    api = Api(client)

    assert len(api.get("/api/v1/analytics/spending-trend", period="day")["buckets"]) == 30
    assert len(api.get("/api/v1/analytics/spending-trend", period="week")["buckets"]) == 12
    assert len(api.get("/api/v1/analytics/spending-trend", period="month")["buckets"]) == 6
    assert len(api.get("/api/v1/analytics/income-expense-trend")["buckets"]) == 6
    assert len(api.get("/api/v1/analytics/spending-trend", period="month", count=24)["buckets"]) == 24
    assert len(api.get("/api/v1/analytics/income-expense-trend", count=24)["buckets"]) == 24
    assert len(api.get("/api/v1/analytics/spending-trend", period="day", count=366)["buckets"]) == 366


def test_money_is_returned_as_exact_two_place_decimal_strings(client: TestClient, clean_database: None) -> None:
    api = Api(client)
    api.income("0.10", "2026-10-02")
    api.income("0.20", "2026-10-03")
    api.expense("0.07", "2026-10-04")

    october = api.overview(2026, 10)

    assert (october["income_total"], october["expense_total"], october["net_flow"]) == ("0.30", "0.07", "0.23")
    assert october["savings_rate_percent"] == "76.67"
    assert api.get("/api/v1/analytics/monthly-summary", year=2026, month=10)["total_spent"] == "0.07"


MONEY_FIELDS = {
    "total_spent", "spent", "remaining", "exceeded_amount", "limit_amount", "average_daily_spending", "daily_spending_allowance",
    "projected_spending", "projected_surplus", "projected_deficit", "income_total", "expense_total", "net_flow", "spent_to_date",
    "current_amount", "target_amount", "remaining_amount", "absolute_change", "current_total_spent", "previous_total_spent",
}
PERCENT_FIELDS = {"utilization_percent", "percent_change", "savings_rate_percent", "progress_percent"}


def _bad_decimals(node: Any, path: str = "") -> List[str]:
    """Every money or percentage value that is not an exact two-place decimal string (null is allowed)."""
    import re

    bad: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in MONEY_FIELDS | PERCENT_FIELDS and value is not None and not re.fullmatch(r"-?\d+\.\d{2}", str(value)):
                bad.append(f"{path}/{key}={value!r}")
            bad += _bad_decimals(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            bad += _bad_decimals(item, f"{path}[{index}]")
    return bad


def test_every_money_and_percentage_is_an_exact_two_place_string_including_zero_and_empty_cases(
    client: TestClient, clean_database: None,
) -> None:
    data = Dataset().build(client)
    a = data.api
    # An untouched Budget (spent 0), an exceeded Budget (remaining 0), an untouched Goal and an empty period.
    a.call("POST", "/api/v1/budgets", 201, json={"name": "Untouched", "limit_amount": "50.00", "period": "monthly", "start_date": "2026-10-01", "category_id": data.rent})
    a.call("POST", "/api/v1/budgets", 201, json={"name": "Exceeded", "limit_amount": "10.00", "period": "monthly", "start_date": "2026-10-01", "category_id": data.food})
    a.call("POST", "/api/v1/goals", 201, json={"name": "Empty goal", "target_amount": "100.00", "currency": "EUR", "target_date": "2027-12-31", "status": "active"})
    funded = a.call("POST", "/api/v1/goals", 201, json={"name": "Funded goal", "target_amount": "100.00", "currency": "EUR", "target_date": "2027-12-31", "status": "active"}).json()
    a.call("POST", f"/api/v1/goals/{funded['id']}/transactions", 201, json={"type": "contribution", "amount": "100.00"})  # remaining 0
    only_unresolved = a.category("Only unresolved")
    with SessionLocal() as session:  # a category whose every expense is unresolved: total 0, never omitted
        session.add(ExpenseModel(user_id=a.user, category_id=only_unresolved, title="legacy", amount=Decimal("5.00"), currency="USD",
                                 expense_date=date(2026, 10, 3), source="manual"))
        session.commit()
    stranger = Api(client)

    for who, payloads in (
        ("dataset", {**views(a), "goal_progress": a.get("/api/v1/analytics/goal-progress"), "aug": a.overview(2026, 8),
                     "category_summary_all": a.get("/api/v1/analytics/category-summary")}),
        ("empty user", {**views(stranger), "goal_progress": stranger.get("/api/v1/analytics/goal-progress")}),
    ):
        for name, payload in payloads.items():
            assert _bad_decimals(payload) == [], f"{who}/{name}"


def test_category_summary_order_is_by_name_and_never_follows_expense_dates_or_insertion_order(client: TestClient, clean_database: None) -> None:
    api = Api(client)
    banana, apple, cherry = api.category("banana"), api.category("Apple"), api.category("cherry")
    # Newest-first insertion in reverse alphabetical order, equal dates for two categories, plus an uncategorized one.
    api.expense("1.00", "2026-10-09", category=cherry)
    api.expense("2.00", "2026-10-09", category=banana)
    api.expense("3.00", "2026-10-08", category=apple)
    api.expense("4.00", "2026-10-07")

    def order() -> List[str]:
        return [c["category_name"] for c in api.get("/api/v1/analytics/category-summary", year=2026, month=10)]

    first = order()
    api.expense("5.00", "2026-10-14", category=apple)  # now Apple has the newest expense
    api.expense("6.00", "2026-10-14")
    with SessionLocal() as session:  # touching rows must not move anything either
        session.execute(text("update expenses set title = title where user_id = :u"), {"u": api.user})
        session.commit()

    assert first == ["Apple", "banana", "cherry", "Uncategorized"]
    assert order() == first
    assert [c["category_name"] for c in api.get("/api/v1/analytics/category-summary")] == first
