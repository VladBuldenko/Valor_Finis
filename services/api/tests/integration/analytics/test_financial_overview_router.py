from datetime import date
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.db.database_session import SessionLocal
from app.modules.analytics import analytics_router
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.fx import fx_ecb_provider, fx_nbu_provider, fx_service
from app.modules.fx.fx_schemas import FxRateResult
from tests.helpers import (
    auth_headers,
    create_account_transaction,
    create_account_transfer,
    create_goal,
    create_goal_transaction,
)

# API tests for GET /api/v1/analytics/financial-overview and
# GET /api/v1/analytics/income-expense-trend (VF-019B).
#
# The endpoints take "today" from analytics_router's date.today(); every
# test freezes ONLY that module-local symbol (the existing _FrozenDate +
# monkeypatch pattern, VF-CI-02), so the expected values hold on any
# calendar day. All fixture dates are in the past relative to the real
# clock, so record creation never depends on it either.

FROZEN_TODAY = date(2026, 10, 2)

OVERVIEW_URL = "/api/v1/analytics/financial-overview"
TREND_URL = "/api/v1/analytics/income-expense-trend"

FIGURE_FIELDS = (
    "income_total", "expense_total", "net_flow", "savings_rate_percent",
    "income_count", "expense_count", "unresolved_income_count", "unresolved_expense_count",
)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return FROZEN_TODAY


def _freeze_today(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "date", _FrozenDate)


# Deterministic stand-in for fx_service.resolve_fx_rate while creating
# foreign-currency records (VF-CI-01 pattern): identity for same-currency
# pairs, a fixed 0.9 rate otherwise - no external provider is reached.
def _deterministic_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
    if original_currency == base_currency:
        return FxRateResult(rate=Decimal("1"), actual_rate_date=transaction_date, source="identity")

    return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")


def _post_income(
    client: TestClient,
    user_id: str,
    amount: str,
    received_at: str,
    currency: str = "EUR",
    source: str = "salary",
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "amount": amount,
        "currency": currency,
        "received_at": received_at,
        "source": source,
    }
    if account_id is not None:
        payload["account_id"] = account_id

    response = client.post("/api/v1/income", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _post_expense(
    client: TestClient,
    user_id: str,
    amount: str,
    expense_date: str,
    currency: str = "EUR",
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Expense",
        "amount": amount,
        "currency": currency,
        "expense_date": expense_date,
        "source": "manual",
    }
    if account_id is not None:
        payload["account_id"] = account_id

    response = client.post("/api/v1/expenses", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _post_account(
    client: TestClient,
    user_id: str,
    name: str,
    opening_balance: Optional[str] = None,
    opening_balance_date: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "type": "checking", "currency": "EUR"}
    if opening_balance is not None:
        payload["opening_balance"] = opening_balance
        payload["opening_balance_date"] = opening_balance_date

    response = client.post("/api/v1/accounts", headers=auth_headers(user_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# Inserts a legacy Expense with no FX snapshot (base_amount NULL) - the
# only way an unresolved Expense exists, since the API always resolves FX.
def _insert_legacy_expense(user_id: str, expense_date: date) -> None:
    db_session = SessionLocal()
    try:
        db_session.add(
            ExpenseModel(
                user_id=user_id, category_id=None, title="Legacy USD", amount=Decimal("999.00"),
                currency="USD", expense_date=expense_date, source="manual",
            )
        )
        db_session.commit()
    finally:
        db_session.close()


def _get_overview(client: TestClient, user_id: str, year: int, month: int):
    return client.get(OVERVIEW_URL, headers=auth_headers(user_id), params={"year": year, "month": month})


# Tests the full single-month contract for a complete month: canonical
# Income (linked, foreign-currency, refund) and Expenses (linked, foreign-
# currency, a legacy unresolved one), with records just outside the month
# excluded, every amount a two-place string, and incomplete data flagged.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date and FX resolution.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the JSON body matches exactly.
def test_financial_overview_endpoint_returns_full_contract(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    monkeypatch.setattr(fx_service, "resolve_fx_rate", _deterministic_resolve_fx_rate)
    user_id = str(uuid4())
    checking = _post_account(client, user_id, "Checking")

    _post_income(client, user_id, "3000.00", "2026-09-01", account_id=checking["id"])
    _post_income(client, user_id, "500.00", "2026-09-15", currency="USD", source="freelance")
    _post_income(client, user_id, "49.90", "2026-09-30", source="refund")
    _post_expense(client, user_id, "1200.00", "2026-09-03", account_id=checking["id"])
    _post_expense(client, user_id, "100.00", "2026-09-12", currency="USD")
    _post_expense(client, user_id, "230.40", "2026-09-30")
    _post_expense(client, user_id, "500.00", "2026-08-31")
    _post_expense(client, user_id, "70.00", "2026-10-01")
    _insert_legacy_expense(user_id, date(2026, 9, 20))

    response = _get_overview(client, user_id, 2026, 9)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "income_total": "3499.90",
        "expense_total": "1520.40",
        "net_flow": "1979.50",
        "savings_rate_percent": "56.56",
        "income_count": 3,
        "expense_count": 3,
        "unresolved_income_count": 0,
        "unresolved_expense_count": 1,
        "base_currency": "EUR",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "as_of": "2026-10-02",
        "effective_end": "2026-09-30",
        "period_state": "complete",
        "data_status": "incomplete_data",
    }


# Tests the month in progress: records through today count, future-dated
# ones do not - while monthly-summary keeps its unchanged whole-month
# semantics for the same month.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only records up to today count in the overview.
def test_financial_overview_current_month_excludes_future_dated_records(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    _post_income(client, user_id, "1000.00", "2026-10-01")
    _post_income(client, user_id, "5000.00", "2026-10-03")
    _post_expense(client, user_id, "300.00", "2026-10-02")
    _post_expense(client, user_id, "700.00", "2026-10-31")

    overview = _get_overview(client, user_id, 2026, 10).json()
    monthly_summary = client.get(
        "/api/v1/analytics/monthly-summary", headers=auth_headers(user_id),
        params={"year": 2026, "month": 10},
    ).json()

    assert overview["period_state"] == "in_progress"
    assert overview["effective_end"] == "2026-10-02"
    assert overview["income_total"] == "1000.00"
    assert overview["expense_total"] == "300.00"
    assert overview["net_flow"] == "700.00"
    assert overview["savings_rate_percent"] == "70.00"
    assert overview["data_status"] == "complete_data"
    assert Decimal(monthly_summary["total_spent"]) == Decimal("1000.00")


# Tests that a future month is a valid request: zeros, null rate and
# effective_end, "future" state - never a 422.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the future state is returned with 200.
def test_financial_overview_future_month(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    _post_income(client, user_id, "5000.00", "2026-11-05")

    response = _get_overview(client, user_id, 2026, 11)

    assert response.status_code == 200
    body = response.json()
    assert body["period_state"] == "future"
    assert body["effective_end"] is None
    assert (body["income_total"], body["expense_total"], body["net_flow"]) == ("0.00", "0.00", "0.00")
    assert body["savings_rate_percent"] is None
    assert body["income_count"] == 0
    assert body["data_status"] == "complete_data"


# Tests the empty-month representation: "0.00" strings, null rate, zero
# counts, complete data.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the empty state is exact.
def test_financial_overview_empty_month(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())

    body = _get_overview(client, user_id, 2026, 8).json()

    assert {field: body[field] for field in FIGURE_FIELDS} == {
        "income_total": "0.00",
        "expense_total": "0.00",
        "net_flow": "0.00",
        "savings_rate_percent": None,
        "income_count": 0,
        "expense_count": 0,
        "unresolved_income_count": 0,
        "unresolved_expense_count": 0,
    }
    assert body["period_state"] == "complete"
    assert body["data_status"] == "complete_data"


# Tests through the API that non-canonical money movements - an opening
# balance, adjustments, a posted Transfer, and Goal contribution/withdrawal
# in the same month - never appear as Income or Expenses, and that an
# Account-linked Income is counted once.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the one Income record counts.
def test_financial_overview_ignores_non_canonical_operations(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    checking = _post_account(client, user_id, "Checking", opening_balance="2000.00", opening_balance_date="2026-09-01")
    savings = _post_account(client, user_id, "Savings")
    create_account_transaction(client, user_id, checking["id"], amount="300.00", direction="credit", transaction_date="2026-09-05")
    create_account_transaction(client, user_id, checking["id"], amount="80.00", direction="debit", transaction_date="2026-09-06")
    transfer = create_account_transfer(
        client, user_id, checking["id"], savings["id"], amount="400.00", transfer_date="2026-09-10",
    )
    assert transfer["status"] == "posted"
    goal = create_goal(client=client, user_id=user_id, name="Trip", target_amount=1000)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=300)
    create_goal_transaction(client=client, user_id=user_id, goal_id=goal["id"], amount=100, type="withdrawal")
    _post_income(client, user_id, "1500.00", "2026-09-15", account_id=checking["id"])

    body = _get_overview(client, user_id, 2026, 9).json()

    assert body["income_total"] == "1500.00"
    assert body["income_count"] == 1
    assert body["expense_total"] == "0.00"
    assert body["expense_count"] == 0
    assert body["net_flow"] == "1500.00"
    assert body["savings_rate_percent"] == "100.00"


# Tests request validation and authentication of the overview: out-of-range
# or missing year/month, and non-integers, are 422; no credentials is 401.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every invalid request is rejected.
def test_financial_overview_validation_and_auth(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())
    invalid_params = [
        {"year": 1999, "month": 5},
        {"year": 2101, "month": 5},
        {"year": 2026, "month": 0},
        {"year": 2026, "month": 13},
        {"year": 2026},
        {"month": 5},
        {"year": "abc", "month": 5},
        {"year": 2026, "month": "x"},
    ]

    for params in invalid_params:
        response = client.get(OVERVIEW_URL, headers=auth_headers(user_id), params=params)
        assert response.status_code == 422, params

    unauthenticated = client.get(OVERVIEW_URL, params={"year": 2026, "month": 9})
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"] == "Missing authentication credentials."


# Tests the trend window through the API: default 6 monthly buckets ending
# with the current month, oldest first, count=1 and count=24 accepted, and
# each bucket identical to the single-month overview of its month.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if windows and per-month figures match.
def test_income_expense_trend_window_and_consistency(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    _post_income(client, user_id, "2000.00", "2026-05-31")
    # June: a tiny deficit whose savings rate rounds to zero - it must be
    # serialized as "0.00", never "-0.00", while net_flow stays "-0.01".
    _post_income(client, user_id, "1000000.00", "2026-06-10")
    _post_expense(client, user_id, "1000000.01", "2026-06-11")
    _post_expense(client, user_id, "150.25", "2026-07-01")
    _post_income(client, user_id, "999.99", "2026-09-30", source="refund")
    _post_expense(client, user_id, "1200.00", "2026-09-30")
    _post_income(client, user_id, "100.00", "2026-10-02")
    _post_expense(client, user_id, "40.00", "2026-10-15")
    _insert_legacy_expense(user_id, date(2026, 8, 8))

    default = client.get(TREND_URL, headers=auth_headers(user_id))

    assert default.status_code == 200, default.text
    body = default.json()
    assert body["count"] == 6
    assert body["as_of"] == "2026-10-02"
    assert body["base_currency"] == "EUR"
    assert [bucket["period_start"] for bucket in body["buckets"]] == [
        "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01",
    ]
    assert body["buckets"][-1]["effective_end"] == "2026-10-02"
    assert body["buckets"][-1]["is_complete"] is False
    assert body["buckets"][-1]["expense_total"] == "0.00"
    assert body["buckets"][3]["unresolved_expense_count"] == 1
    assert body["buckets"][1]["net_flow"] == "-0.01"
    assert body["buckets"][1]["savings_rate_percent"] == "0.00"
    june_overview = _get_overview(client, user_id, 2026, 6).json()
    assert june_overview["net_flow"] == "-0.01"
    assert june_overview["savings_rate_percent"] == "0.00"

    for bucket in body["buckets"]:
        year, month = int(bucket["period_start"][:4]), int(bucket["period_start"][5:7])
        overview = _get_overview(client, user_id, year, month).json()
        assert {field: bucket[field] for field in FIGURE_FIELDS} == {
            field: overview[field] for field in FIGURE_FIELDS
        }, bucket["period_start"]
        assert bucket["effective_end"] == overview["effective_end"]

    single = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 1}).json()
    longest = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 24}).json()
    assert [bucket["period_start"] for bucket in single["buckets"]] == ["2026-10-01"]
    assert len(longest["buckets"]) == 24
    assert longest["buckets"][0]["period_start"] == "2024-11-01"


# Tests trend request validation and authentication: count outside 1..24
# or non-integer is 422; no credentials is 401.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every invalid request is rejected.
def test_income_expense_trend_validation_and_auth(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid4())

    for count in (0, 25, -1, "abc", "1.5"):
        response = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": count})
        assert response.status_code == 422, count

    unauthenticated = client.get(TREND_URL)
    assert unauthenticated.status_code == 401


# Tests user isolation through the API: another user's Income, Expenses,
# and unresolved rows never affect the overview or the trend, while that
# user still sees their own records (positive control).
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each user sees only their own records.
def test_financial_overview_and_trend_are_user_scoped(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    _post_income(client, other_user_id, "9000.00", "2026-09-01")
    _post_expense(client, other_user_id, "800.00", "2026-09-02")
    _insert_legacy_expense(other_user_id, date(2026, 9, 3))

    overview = _get_overview(client, user_id, 2026, 9).json()
    trend = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 2}).json()

    assert overview["income_total"] == "0.00"
    assert overview["expense_total"] == "0.00"
    assert overview["unresolved_expense_count"] == 0
    assert overview["data_status"] == "complete_data"
    assert all(
        (bucket["income_total"], bucket["expense_total"], bucket["unresolved_expense_count"])
        == ("0.00", "0.00", 0)
        for bucket in trend["buckets"]
    )

    # Positive control: the other user does see their own records through
    # both endpoints, so the zeros above come from user scoping, not from
    # the records being invisible to everyone.
    other_overview = _get_overview(client, other_user_id, 2026, 9).json()
    other_september = client.get(
        TREND_URL, headers=auth_headers(other_user_id), params={"count": 2},
    ).json()["buckets"][0]

    for figures in (other_overview, other_september):
        assert figures["income_total"] == "9000.00"
        assert figures["expense_total"] == "800.00"
        assert (figures["income_count"], figures["expense_count"]) == (1, 1)
        assert figures["unresolved_expense_count"] == 1
    assert other_overview["data_status"] == "incomplete_data"
    assert other_september["period_start"] == "2026-09-01"


# Tests that reading the overview and the trend never resolves FX or calls
# an FX provider - the persisted snapshots are the only source.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date and observe FX.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if no FX call happens during the reads.
def test_financial_overview_reads_never_call_fx(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    monkeypatch.setattr(fx_service, "resolve_fx_rate", _deterministic_resolve_fx_rate)
    user_id = str(uuid4())
    _post_income(client, user_id, "200.00", "2026-09-10", currency="USD")
    _post_expense(client, user_id, "50.00", "2026-09-11", currency="USD")

    resolve_spy = MagicMock(side_effect=AssertionError("analytics reads must never resolve FX"))
    ecb_get = MagicMock()
    nbu_get = MagicMock()
    monkeypatch.setattr(fx_service, "resolve_fx_rate", resolve_spy)
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_get)
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", nbu_get)

    overview = _get_overview(client, user_id, 2026, 9)
    trend = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 2})

    assert overview.status_code == 200 and trend.status_code == 200
    assert overview.json()["income_total"] == "180.00"
    assert overview.json()["expense_total"] == "45.00"
    resolve_spy.assert_not_called()
    ecb_get.assert_not_called()
    nbu_get.assert_not_called()


def _patch(client: TestClient, user_id: str, url: str, payload: dict[str, Any]) -> None:
    response = client.patch(url, headers=auth_headers(user_id), json=payload)
    assert response.status_code == 200, response.text


def _delete(client: TestClient, user_id: str, url: str) -> None:
    response = client.delete(url, headers=auth_headers(user_id))
    assert response.status_code == 204, response.text


def _account_balance(client: TestClient, user_id: str, account_id: str) -> Decimal:
    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    [account] = [account for account in response.json() if account["id"] == account_id]
    return Decimal(account["current_balance"])


def _month_figures(client: TestClient, user_id: str, year: int, month: int) -> dict[str, Any]:
    body = _get_overview(client, user_id, year, month).json()
    return {field: body[field] for field in FIGURE_FIELDS}


# Tests that the overview and the trend follow every Income mutation
# (VF-019D): create, an amount change, a date move to another month,
# detaching from the Account, and delete - for an Account-linked and an
# unlinked Income. The linked Income's ledger projection really exists
# (the Account balance follows it) yet is never counted a second time, and
# another user's Income never leaks in (positive control at the end).
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every step shows the expected figures.
def test_financial_overview_follows_income_mutations(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    checking = _post_account(client, user_id, "Checking")
    _post_income(client, other_user_id, "9999.00", "2026-09-15")

    linked = _post_income(client, user_id, "1000.00", "2026-09-10", account_id=checking["id"])
    unlinked = _post_income(client, user_id, "200.00", "2026-09-12", source="freelance")

    september = _month_figures(client, user_id, 2026, 9)
    assert (september["income_total"], september["income_count"]) == ("1200.00", 2)
    assert (september["net_flow"], september["savings_rate_percent"]) == ("1200.00", "100.00")
    assert _account_balance(client, user_id, checking["id"]) == Decimal("1000.00")

    # Update the linked Income's amount: counted once, projection follows.
    _patch(client, user_id, f"/api/v1/income/{linked['id']}", {"amount": "1500.00"})
    september = _month_figures(client, user_id, 2026, 9)
    assert (september["income_total"], september["income_count"]) == ("1700.00", 2)
    assert _account_balance(client, user_id, checking["id"]) == Decimal("1500.00")

    # Move the unlinked Income to August: it leaves September for August.
    _patch(client, user_id, f"/api/v1/income/{unlinked['id']}", {"received_at": "2026-08-20"})
    september = _month_figures(client, user_id, 2026, 9)
    august = _month_figures(client, user_id, 2026, 8)
    assert (september["income_total"], september["income_count"]) == ("1500.00", 1)
    assert (august["income_total"], august["income_count"]) == ("200.00", 1)

    # Detach the linked Income: the projection disappears, the Income stays.
    _patch(client, user_id, f"/api/v1/income/{linked['id']}", {"account_id": None})
    september = _month_figures(client, user_id, 2026, 9)
    assert (september["income_total"], september["income_count"]) == ("1500.00", 1)
    assert _account_balance(client, user_id, checking["id"]) == Decimal("0")

    # Delete it: September has no income left, so the rate is unavailable.
    _delete(client, user_id, f"/api/v1/income/{linked['id']}")
    september = _month_figures(client, user_id, 2026, 9)
    assert september == {
        "income_total": "0.00",
        "expense_total": "0.00",
        "net_flow": "0.00",
        "savings_rate_percent": None,
        "income_count": 0,
        "expense_count": 0,
        "unresolved_income_count": 0,
        "unresolved_expense_count": 0,
    }

    trend = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 3}).json()
    assert [
        (bucket["period_start"], bucket["income_total"], bucket["income_count"])
        for bucket in trend["buckets"]
    ] == [
        ("2026-08-01", "200.00", 1),
        ("2026-09-01", "0.00", 0),
        ("2026-10-01", "0.00", 0),
    ]

    other_september = _month_figures(client, other_user_id, 2026, 9)
    assert (other_september["income_total"], other_september["income_count"]) == ("9999.00", 1)


# Tests that the overview and the trend follow every Expense mutation
# (VF-019D): create, an amount change, attaching an unlinked Expense to the
# Account, a date move into the current month, and delete. Net and the
# savings rate move with the totals, attaching never double-counts through
# the new ledger projection, and another user's Expense never leaks in.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to freeze the date.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every step shows the expected figures.
def test_financial_overview_follows_expense_mutations(
    client: TestClient,
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    _freeze_today(monkeypatch)
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    checking = _post_account(client, user_id, "Checking")
    _post_expense(client, other_user_id, "777.00", "2026-09-07")
    _post_income(client, user_id, "1000.00", "2026-09-01")

    linked = _post_expense(client, user_id, "300.00", "2026-09-05", account_id=checking["id"])
    unlinked = _post_expense(client, user_id, "45.50", "2026-09-06")

    september = _month_figures(client, user_id, 2026, 9)
    assert (september["expense_total"], september["expense_count"]) == ("345.50", 2)
    assert (september["net_flow"], september["savings_rate_percent"]) == ("654.50", "65.45")
    assert _account_balance(client, user_id, checking["id"]) == Decimal("-300.00")

    # Update the linked Expense's amount.
    _patch(client, user_id, f"/api/v1/expenses/{linked['id']}", {"amount": "400.00"})
    september = _month_figures(client, user_id, 2026, 9)
    assert (september["expense_total"], september["expense_count"]) == ("445.50", 2)
    assert (september["net_flow"], september["savings_rate_percent"]) == ("554.50", "55.45")

    # Attach the unlinked Expense to the Account: a projection is created,
    # the Expense is still counted exactly once.
    _patch(client, user_id, f"/api/v1/expenses/{unlinked['id']}", {"account_id": checking["id"]})
    september = _month_figures(client, user_id, 2026, 9)
    assert (september["expense_total"], september["expense_count"]) == ("445.50", 2)
    assert _account_balance(client, user_id, checking["id"]) == Decimal("-445.50")

    # Move it into the current month: it leaves September for October.
    _patch(client, user_id, f"/api/v1/expenses/{unlinked['id']}", {"expense_date": "2026-10-01"})
    september = _month_figures(client, user_id, 2026, 9)
    october = _get_overview(client, user_id, 2026, 10).json()
    assert (september["expense_total"], september["expense_count"]) == ("400.00", 1)
    assert (september["net_flow"], september["savings_rate_percent"]) == ("600.00", "60.00")
    assert october["period_state"] == "in_progress"
    assert (october["expense_total"], october["expense_count"]) == ("45.50", 1)
    assert (october["net_flow"], october["savings_rate_percent"]) == ("-45.50", None)

    # Delete the first Expense: September keeps only its income.
    _delete(client, user_id, f"/api/v1/expenses/{linked['id']}")
    september = _month_figures(client, user_id, 2026, 9)
    assert (september["expense_total"], september["expense_count"]) == ("0.00", 0)
    assert (september["net_flow"], september["savings_rate_percent"]) == ("1000.00", "100.00")
    assert _account_balance(client, user_id, checking["id"]) == Decimal("-45.50")

    trend = client.get(TREND_URL, headers=auth_headers(user_id), params={"count": 2}).json()
    assert [
        (bucket["period_start"], bucket["income_total"], bucket["expense_total"], bucket["net_flow"])
        for bucket in trend["buckets"]
    ] == [
        ("2026-09-01", "1000.00", "0.00", "1000.00"),
        ("2026-10-01", "0.00", "45.50", "-45.50"),
    ]

    other_september = _month_figures(client, other_user_id, 2026, 9)
    assert (other_september["expense_total"], other_september["expense_count"]) == ("777.00", 1)
