from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.fx import fx_ecb_provider
from tests.helpers import (
    auth_headers,
    create_budget,
    create_category,
    create_expense,
    create_goal,
)


# Mocks the ECB provider HTTP boundary for tests that need a resolved
# foreign-currency FX snapshot on expense creation.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# - rate: ECB's published rate (units of currency per 1 EUR).
# - actual_date: the observation date ECB reports back.
# Returns:
# - The MagicMock installed as fx_ecb_provider.httpx.get, so a test can
#   assert_not_called()/reset_mock() on it later.
def _mock_ecb(monkeypatch, rate: float, actual_date: str) -> MagicMock:
    payload = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [rate, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": actual_date}]}]}},
    }
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    get_mock = MagicMock(return_value=response)
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)
    return get_mock


# Computes the inclusive [start, end] bounds of the calendar month
# containing a date.
# This helper exists so integration tests can assert exact period
# boundaries against dynamically computed (date.today()-relative) fixture
# dates instead of hardcoded, wall-clock-fragile literals - the budget-
# status endpoint no longer accepts a public as_of, so these tests must
# always exercise the real current period.
# Parameters:
# - d: a date within the target month.
# Returns:
# - (month_start, month_end) tuple.
def month_bounds(d: date) -> tuple:
    start = d.replace(day=1)
    next_start = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, next_start - timedelta(days=1)


# Computes the inclusive [Monday, Sunday] bounds of the calendar week
# containing a date. See month_bounds for why this exists.
def week_bounds(d: date) -> tuple:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


# Creates a budget with explicit period/date/currency fields for B3 tests.
# This helper exists because tests/helpers.py's create_budget hardcodes
# period=monthly/start_date=2026-05-01/currency=EUR, which most of the
# calendar-period scenarios below need to vary.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - start_date/end_date/period/currency/category_id/name/limit_amount: see
#   the backend BudgetCreate schema.
# Returns:
# - Created budget response body.
def create_budget_with(
    client: TestClient,
    user_id: str,
    start_date: str,
    end_date: Optional[str] = None,
    period: str = "monthly",
    currency: str = "EUR",
    category_id: Optional[str] = None,
    name: str = "Budget",
    limit_amount: float = 100,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/budgets",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "name": name,
            "limit_amount": limit_amount,
            "currency": currency,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# Creates an expense with an explicit expense_date/currency for B3 tests.
# This helper exists because tests/helpers.py's create_expense hardcodes
# expense_date=2026-05-07/currency=EUR.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - expense_date/currency/category_id/amount/title: see the backend
#   ExpenseCreate schema.
# Returns:
# - Created expense response body.
def create_expense_with(
    client: TestClient,
    user_id: str,
    expense_date: str,
    currency: str = "EUR",
    category_id: Optional[str] = None,
    amount: float = 10,
    title: str = "Expense",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "title": title,
            "amount": amount,
            "currency": currency,
            "expense_date": expense_date,
            "description": title,
            "source": "manual",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# Tests that the monthly summary endpoint returns total spending data for a selected month.
# This test exists to verify that analytics monthly summary is exposed through the API
# and requires year/month query parameters.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns correct monthly summary values.
def test_monthly_summary_endpoint_returns_summary(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Groceries",
        amount=50,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["total_spent"] == "50.00"
    assert response_data["expenses_count"] == 1


# Tests that the monthly summary endpoint filters expenses by selected month and authenticated user.
# This test exists to verify that expenses from other months and other users are not included.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only matching expenses are included in the summary.
def test_monthly_summary_endpoint_filters_by_month_and_user(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    current_month_expense = {
        "category_id": None,
        "title": "May groceries",
        "amount": 50,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "May groceries",
        "source": "manual",
    }
    other_month_expense = {
        "category_id": None,
        "title": "June groceries",
        "amount": 70,
        "currency": "EUR",
        "expense_date": "2026-06-07",
        "description": "June groceries",
        "source": "manual",
    }
    other_user_expense = {
        "category_id": None,
        "title": "Other user groceries",
        "amount": 999,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Other user groceries",
        "source": "manual",
    }

    client.post(
        "/api/v1/expenses",
        json=current_month_expense,
        headers=auth_headers(user_id),
    )
    client.post(
        "/api/v1/expenses",
        json=other_month_expense,
        headers=auth_headers(user_id),
    )
    client.post(
        "/api/v1/expenses",
        json=other_user_expense,
        headers=auth_headers(other_user_id),
    )

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["total_spent"] == "50.00"
    assert response_data["expenses_count"] == 1

# Tests that the monthly summary endpoint returns zero values for a month without expenses.
# This test exists to verify that empty monthly analytics responses are safe for dashboards.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if empty month summary values are returned.
def test_monthly_summary_endpoint_returns_zero_for_empty_month(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Groceries",
        amount=50,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=6",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["total_spent"] in ["0", "0.00"]
    assert response_data["expenses_count"] == 0

# Tests that the monthly summary endpoint rejects invalid month query parameter.
# This test exists to verify FastAPI query validation for monthly analytics.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_monthly_summary_endpoint_rejects_invalid_month(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=13",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the category summary endpoint groups expenses by category.
# This test exists to verify category analytics API calculations.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if grouped category totals are returned correctly.
def test_category_summary_endpoint_returns_grouped_categories(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )
    category_id = category["id"]

    create_expense(
        client=client,
        user_id=user_id,
        category_id=category_id,
        title="Groceries",
        amount=20,
    )
    create_expense(
        client=client,
        user_id=user_id,
        category_id=category_id,
        title="Dinner",
        amount=30,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-summary",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["category_id"] == category_id
    assert response_data[0]["category_name"] == "Food"
    assert response_data[0]["total_spent"] == "50.00"
    assert response_data[0]["expenses_count"] == 2

# Tests that category summary filters expenses by the selected month.
# This test exists to verify that year and month query parameters
# are passed through the API and applied to category analytics.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only expenses from the selected month are returned.
def test_category_summary_endpoint_filters_by_selected_month(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )
    category_id = category["id"]

    may_expense_one = {
        "category_id": category_id,
        "title": "May groceries",
        "amount": 20,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "May groceries",
        "source": "manual",
    }
    may_expense_two = {
        "category_id": category_id,
        "title": "May dinner",
        "amount": 30,
        "currency": "EUR",
        "expense_date": "2026-05-20",
        "description": "May dinner",
        "source": "manual",
    }
    june_expense = {
        "category_id": category_id,
        "title": "June groceries",
        "amount": 70,
        "currency": "EUR",
        "expense_date": "2026-06-07",
        "description": "June groceries",
        "source": "manual",
    }

    client.post(
        "/api/v1/expenses",
        json=may_expense_one,
        headers=auth_headers(user_id),
    )
    client.post(
        "/api/v1/expenses",
        json=may_expense_two,
        headers=auth_headers(user_id),
    )
    client.post(
        "/api/v1/expenses",
        json=june_expense,
        headers=auth_headers(user_id),
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["category_id"] == category_id
    assert response_data[0]["category_name"] == "Food"
    assert response_data[0]["total_spent"] == "50.00"
    assert response_data[0]["expenses_count"] == 2

# Tests that category summary requires year and month to be provided together.
# This test exists to prevent ambiguous partial date filters in the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if partial date filters are rejected.
def test_category_summary_endpoint_rejects_partial_date_filter(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    urls = [
        "/api/v1/analytics/category-summary?year=2026",
        "/api/v1/analytics/category-summary?month=5",
    ]

    # Act and Assert
    for url in urls:
        response = client.get(
            url,
            headers=auth_headers(user_id),
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Year and month must be provided together."
        )


# ---------------------------------------------------------------------------
# VF-014B5D base-currency spending (monthly-summary / category-summary)
# ---------------------------------------------------------------------------


# Tests (A) that monthly summary sums base_amount, not the original mixed-
# currency amount, for a EUR expense plus a resolved USD-original expense -
# and (I) that the underlying Expense response still carries both original
# and base monetary truth unchanged.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if total_spent == 184.73, not 200.
def test_monthly_summary_endpoint_sums_base_amount_across_currencies(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.1803, actual_date="2026-05-07")  # 100 USD -> 84.73 EUR

    create_expense_with(client=client, user_id=user_id, expense_date="2026-05-07", currency="EUR", amount=100)
    usd_expense = create_expense_with(
        client=client, user_id=user_id, expense_date="2026-05-07", currency="USD", amount=100,
    )

    # (I) the underlying Expense response still exposes original + base truth.
    assert usd_expense["amount"] == "100.00"
    assert usd_expense["currency"] == "USD"
    assert usd_expense["base_currency"] == "EUR"
    assert usd_expense["base_amount"] is not None

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert response.status_code == 200
    assert Decimal(body["total_spent"]) == Decimal("100.00") + Decimal(usd_expense["base_amount"])
    assert body["total_spent"] != "200.00"
    assert body["expenses_count"] == 2
    assert body["base_currency"] == "EUR"
    assert body["unresolved_expenses_count"] == 0


# Tests (B) that category summary sums base_amount, not the original
# mixed-currency amount, for expenses of different original currencies in
# the same category.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the category's total_spent uses base_amount.
def test_category_summary_endpoint_sums_base_amount_across_currencies(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    category = create_category(client=client, user_id=user_id, name="Business Trips")
    _mock_ecb(monkeypatch, rate=1.1803, actual_date="2026-05-07")

    create_expense_with(
        client=client, user_id=user_id, expense_date="2026-05-07", currency="EUR",
        amount=100, category_id=category["id"],
    )
    usd_expense = create_expense_with(
        client=client, user_id=user_id, expense_date="2026-05-07", currency="USD",
        amount=100, category_id=category["id"],
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-summary",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()[0]
    assert Decimal(body["total_spent"]) == Decimal("100.00") + Decimal(usd_expense["base_amount"])
    assert body["total_spent"] != "200.00"
    assert body["expenses_count"] == 2
    assert body["unresolved_expenses_count"] == 0
    assert body["base_currency"] == "EUR"


# Tests (C) that a legacy unresolved Expense (simulating one created
# before VF-014B5C) leaves the monetary total unchanged and is exposed
# through unresolved_expenses_count, never counted as zero-valued.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if total_spent reflects only the resolved
#   expense and unresolved_expenses_count reflects the legacy one.
def test_monthly_summary_endpoint_unresolved_legacy_expense_exposed(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    user_id = str(user_id_uuid)

    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=None,
        title="Legacy USD",
        amount=Decimal("999.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    db_session.close()

    create_expense_with(client=client, user_id=user_id, expense_date="2026-05-07", currency="EUR", amount=50)

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert body["total_spent"] == "50.00"
    assert body["expenses_count"] == 1
    assert body["unresolved_expenses_count"] == 1


# Tests (D) that a category whose only matching expense is a legacy
# unresolved one is still returned, not silently omitted.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the unresolved-only category appears with
#   total_spent=0 and unresolved_expenses_count > 0.
def test_category_summary_endpoint_unresolved_only_category_still_appears(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    user_id = str(user_id_uuid)
    category = create_category(client=client, user_id=user_id, name="Legacy category")

    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=category["id"],
        title="Legacy USD",
        amount=Decimal("999.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    db_session.close()

    # Act
    response = client.get(
        "/api/v1/analytics/category-summary",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body) == 1
    assert body[0]["category_id"] == category["id"]
    assert body[0]["total_spent"] == "0" or body[0]["total_spent"] == "0.00"
    assert body[0]["expenses_count"] == 0
    assert body[0]["unresolved_expenses_count"] == 1


# Tests (E) that a zero-expense user's monthly summary still returns their
# correct base_currency (lazily bootstrapped to EUR on first access).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if base_currency is EUR with zero expenses.
def test_monthly_summary_endpoint_zero_expenses_returns_base_currency(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert body["total_spent"] in ["0", "0.00"]
    assert body["expenses_count"] == 0
    assert body["unresolved_expenses_count"] == 0
    assert body["base_currency"] == "EUR"


# Tests (F, G) that monthly and category summaries are scoped to the
# authenticated user only - another user's expenses never leak in.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if user B's totals/categories are empty despite
#   user A's spending.
def test_summary_endpoints_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_a = str(uuid4())
    user_b = str(uuid4())
    category = create_category(client=client, user_id=user_a, name="Food")

    create_expense_with(
        client=client, user_id=user_a, expense_date="2026-05-07", amount=500, category_id=category["id"],
    )

    # Act
    monthly_response = client.get(
        "/api/v1/analytics/monthly-summary?year=2026&month=5",
        headers=auth_headers(user_b),
    )
    category_response = client.get(
        "/api/v1/analytics/category-summary",
        headers=auth_headers(user_b),
    )

    # Assert
    assert monthly_response.json()["total_spent"] in ["0", "0.00"]
    assert monthly_response.json()["expenses_count"] == 0
    assert category_response.json() == []


# Tests (J) that no FX provider is ever called while serving a monthly-
# summary or category-summary request, even though a resolved foreign-
# currency Expense (created earlier, with the provider mocked separately)
# is included in the totals - analytics only ever reads the already-
# persisted base_amount, it never resolves FX itself.
# ECB and NBU providers both call the module-level `httpx.get` - and
# fx_ecb_provider.httpx / fx_nbu_provider.httpx are the same imported
# module object - so mocking it once and asserting it is not called again
# proves neither provider's HTTP path was exercised by the analytics GETs.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if httpx.get is not called during either
#   analytics GET request.
def test_summary_endpoints_never_call_fx_providers(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1803, actual_date="2026-05-07")

    create_expense_with(client=client, user_id=user_id, expense_date="2026-05-07", currency="USD", amount=100)
    ecb_mock.reset_mock()

    # Act
    client.get("/api/v1/analytics/monthly-summary?year=2026&month=5", headers=auth_headers(user_id))
    client.get("/api/v1/analytics/category-summary", headers=auth_headers(user_id))

    # Assert
    ecb_mock.assert_not_called()


# Tests (K) that Budget Status is unaffected by VF-014B5D: it still
# evaluates using the expense's original currency against the budget's
# currency, not base_amount, even when a resolved foreign-currency
# expense (with a real base_amount) exists in the same request context as
# the analytics endpoints above.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if budget-status excludes the foreign-currency
#   expense exactly as B3/B4 already required, unaffected by base_amount.
def test_budget_status_endpoint_unaffected_by_base_currency_analytics(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="EUR budget", limit_amount=100, currency="EUR",
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=20, currency="EUR")
    # A resolved foreign-currency expense with a real, non-null base_amount -
    # Budget Status must still ignore it entirely (original-currency rule).
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=999, currency="USD")

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.json()[0]["spent"] == "20.00"


# ---------------------------------------------------------------------------
# VF-015B spending trend
# ---------------------------------------------------------------------------


# Tests (A) that the current month's bucket sums base_amount across a EUR
# and a USD-original resolved expense - the same worked example as B5D
# (100 EUR + 100 USD/84.73 EUR-base -> 184.73, not 200).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if total_spent == 184.73 for the current bucket.
def test_spending_trend_endpoint_sums_base_amount_across_currencies(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), currency="EUR", amount=100)
    usd_expense = create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), currency="USD", amount=100,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_currency"] == "EUR"
    current_bucket = body["buckets"][-1]
    assert Decimal(current_bucket["total_spent"]) == Decimal("100.00") + Decimal(usd_expense["base_amount"])
    assert current_bucket["total_spent"] != "200.00"
    assert current_bucket["expenses_count"] == 2
    assert current_bucket["unresolved_expenses_count"] == 0


# Tests (B) that an empty period inside the requested window is emitted as
# an explicit zero bucket rather than omitted.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if all requested buckets are present and the
#   empty one reads exactly "0.00".
def test_spending_trend_endpoint_emits_zero_buckets_for_empty_periods(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange - two months ago has an expense, one month ago has none, this
    # month has an expense: three buckets total, middle one empty.
    user_id = str(uuid4())
    today = date.today()
    two_months_ago = date(today.year, today.month, 1)
    for _ in range(2):
        two_months_ago = (
            date(two_months_ago.year - 1, 12, 1)
            if two_months_ago.month == 1
            else date(two_months_ago.year, two_months_ago.month - 1, 1)
        )

    create_expense_with(client=client, user_id=user_id, expense_date=two_months_ago.isoformat(), amount=100)
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=50)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=3",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["buckets"]) == 3
    assert Decimal(body["buckets"][0]["total_spent"]) == Decimal("100.00")
    assert body["buckets"][1]["total_spent"] == "0.00"
    assert body["buckets"][1]["expenses_count"] == 0
    assert Decimal(body["buckets"][2]["total_spent"]) == Decimal("50.00")


# Tests (C) that the current bucket is marked incomplete and a future-dated
# expense within it does not leak into the total.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if is_complete is false and the future expense
#   is excluded from total_spent.
def test_spending_trend_endpoint_current_bucket_incomplete_future_excluded(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    _, month_end = month_bounds(today)

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=20)
    if today < month_end:
        future_date = today + timedelta(days=1)
        create_expense_with(client=client, user_id=user_id, expense_date=future_date.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    current_bucket = body["buckets"][-1]
    assert current_bucket["is_complete"] is False
    assert current_bucket["effective_end"] == today.isoformat()
    assert Decimal(current_bucket["total_spent"]) == Decimal("20.00")


# Tests (day/week buckets) that day and week period granularities resolve
# through the real API with correct calendar boundaries.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if day buckets are single dates and the week
#   bucket runs Monday-Sunday.
def test_spending_trend_endpoint_day_and_week_buckets(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    week_start, week_end = week_bounds(today)

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=15)

    # Act - day
    day_response = client.get(
        "/api/v1/analytics/spending-trend?period=day&count=1",
        headers=auth_headers(user_id),
    )
    # Act - week
    week_response = client.get(
        "/api/v1/analytics/spending-trend?period=week&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    day_bucket = day_response.json()["buckets"][-1]
    assert day_bucket["period_start"] == day_bucket["period_end"] == today.isoformat()
    assert Decimal(day_bucket["total_spent"]) == Decimal("15.00")

    week_bucket = week_response.json()["buckets"][-1]
    assert week_bucket["period_start"] == week_start.isoformat()
    assert week_bucket["period_end"] == week_end.isoformat()
    assert Decimal(week_bucket["total_spent"]) == Decimal("15.00")


# Tests that period_over_period compares the two most recent complete
# buckets using real data, never the current partial one.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the comparison reflects the two completed
#   months, not the current one.
def test_spending_trend_endpoint_period_over_period_uses_complete_buckets(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, _ = month_bounds(today)
    last_month_end = month_start - timedelta(days=1)
    last_month_start, _ = month_bounds(last_month_end)
    two_months_ago_end = last_month_start - timedelta(days=1)

    create_expense_with(client=client, user_id=user_id, expense_date=two_months_ago_end.isoformat(), amount=100)
    create_expense_with(client=client, user_id=user_id, expense_date=last_month_end.isoformat(), amount=150)
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=3",
        headers=auth_headers(user_id),
    )

    # Assert
    comparison = response.json()["period_over_period"]
    assert comparison is not None
    assert Decimal(comparison["previous_total_spent"]) == Decimal("100.00")
    assert Decimal(comparison["current_total_spent"]) == Decimal("150.00")
    assert comparison["direction"] == "up"


# Tests (FX) that a legacy unresolved expense is excluded from the bucket
# total and counted separately.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if total_spent excludes the legacy row and
#   unresolved_expenses_count reflects it.
def test_spending_trend_endpoint_unresolved_legacy_expense_excluded(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    user_id = str(user_id_uuid)
    today = date.today()

    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=None,
        title="Legacy USD",
        amount=Decimal("999.00"),
        currency="USD",
        expense_date=today,
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    db_session.close()

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=50)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    current_bucket = response.json()["buckets"][-1]
    assert Decimal(current_bucket["total_spent"]) == Decimal("50.00")
    assert current_bucket["unresolved_expenses_count"] == 1


# Tests (security) that spending trend is scoped to the authenticated user.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if another user's expenses never appear.
def test_spending_trend_endpoint_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    today = date.today()

    create_expense_with(client=client, user_id=other_user_id, expense_date=today.isoformat(), amount=500)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    current_bucket = response.json()["buckets"][-1]
    assert current_bucket["total_spent"] == "0.00"
    assert current_bucket["expenses_count"] == 0


# Tests (network) that no FX provider is ever called while serving a
# spending-trend request, even though a resolved foreign-currency expense
# (created earlier, with the provider mocked separately) is included.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if httpx.get is not called during the trend request.
def test_spending_trend_endpoint_never_calls_fx_providers(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), currency="USD", amount=100)
    ecb_mock.reset_mock()

    # Act
    client.get("/api/v1/analytics/spending-trend?period=month&count=3", headers=auth_headers(user_id))

    # Assert
    ecb_mock.assert_not_called()


# Tests (zero data) that a brand-new user still receives the full requested
# set of zero buckets and their correct authoritative base_currency.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if 3 zero buckets and base_currency "EUR" return.
def test_spending_trend_endpoint_zero_data_new_user(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=3",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert len(body["buckets"]) == 3
    for bucket in body["buckets"]:
        assert bucket["total_spent"] == "0.00"
        assert bucket["expenses_count"] == 0
        assert bucket["unresolved_expenses_count"] == 0
    assert body["period_over_period"] is not None
    assert body["period_over_period"]["direction"] == "unchanged"
    assert body["period_over_period"]["percent_change"] is None


# Tests (validation) that an unsupported period value is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 422.
def test_spending_trend_endpoint_rejects_unsupported_period(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=year&count=3",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    assert response.status_code == 422


# Tests (validation) that count below 1 is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 422.
def test_spending_trend_endpoint_rejects_count_below_one(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        "/api/v1/analytics/spending-trend?period=month&count=0",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    assert response.status_code == 422


# Tests (validation) that count above the per-period maximum is rejected,
# for all three supported periods.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each period's over-maximum count is rejected.
def test_spending_trend_endpoint_rejects_count_above_maximum(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    over_maximum_counts = {"day": 367, "week": 105, "month": 25}

    for period, count in over_maximum_counts.items():
        # Act
        response = client.get(
            f"/api/v1/analytics/spending-trend?period={period}&count={count}",
            headers=auth_headers(user_id),
        )

        # Assert
        assert response.status_code == 422, (period, response.text)


# Tests (validation) that the default count is applied per period when
# count is omitted.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the returned bucket count matches each
#   period's documented default.
def test_spending_trend_endpoint_default_counts_applied(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    expected_defaults = {"day": 30, "week": 12, "month": 6}

    for period, expected_count in expected_defaults.items():
        # Act
        response = client.get(
            f"/api/v1/analytics/spending-trend?period={period}",
            headers=auth_headers(user_id),
        )

        # Assert
        body = response.json()
        assert body["count"] == expected_count
        assert len(body["buckets"]) == expected_count


# ---------------------------------------------------------------------------
# VF-015C category spending trends
# ---------------------------------------------------------------------------


# Tests (CATEGORY GROUPING A) that multiple categories are computed
# independently, each summing only its own resolved base_amount.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if each category's current-bucket total reflects
#   only its own Expenses.
def test_category_trend_endpoint_multiple_categories_independent(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    food = create_category(client=client, user_id=user_id, name="Food")
    hobbies = create_category(client=client, user_id=user_id, name="Hobbies")

    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=20, category_id=food["id"],
    )
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=40, category_id=hobbies["id"],
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {c["category_id"]: c for c in body["categories"]}
    assert Decimal(by_id[food["id"]]["buckets"][0]["total_spent"]) == Decimal("20.00")
    assert Decimal(by_id[hobbies["id"]]["buckets"][0]["total_spent"]) == Decimal("40.00")
    assert body["base_currency"] == "EUR"


# Tests (CATEGORY GROUPING - Uncategorized) that an Expense with no
# category appears under Uncategorized.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if a category_id: null item named "Uncategorized" appears.
def test_category_trend_endpoint_uncategorized(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=15, category_id=None)

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["categories"]) == 1
    assert body["categories"][0]["category_id"] is None
    assert body["categories"][0]["category_name"] == "Uncategorized"


# Tests (CATEGORY GROUPING) that a category whose only matching Expense is
# a legacy unresolved row still appears, with a zero total and a nonzero
# unresolved count.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the category is present with total "0.00".
def test_category_trend_endpoint_unresolved_only_category_remains_present(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    user_id = str(user_id_uuid)
    today = date.today()
    category = create_category(client=client, user_id=user_id, name="Legacy category")

    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=category["id"],
        title="Legacy USD",
        amount=Decimal("999.00"),
        currency="USD",
        expense_date=today,
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    db_session.close()

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["categories"]) == 1
    item = body["categories"][0]
    assert item["category_id"] == category["id"]
    assert item["buckets"][0]["total_spent"] == "0.00"
    assert item["buckets"][0]["unresolved_expenses_count"] == 1


# Tests (FILTER) that an owned category_id returns exactly one category,
# scoped only to that category, even when other categories have Expenses
# in the same range.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the requested category is returned.
def test_category_trend_endpoint_owned_category_filter(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    food = create_category(client=client, user_id=user_id, name="Food")
    hobbies = create_category(client=client, user_id=user_id, name="Hobbies")
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=20, category_id=food["id"],
    )
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=999, category_id=hobbies["id"],
    )

    # Act
    response = client.get(
        f"/api/v1/analytics/category-trend?period=month&count=1&category_id={food['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["categories"]) == 1
    assert body["categories"][0]["category_id"] == food["id"]
    assert Decimal(body["categories"][0]["buckets"][0]["total_spent"]) == Decimal("20.00")


# Tests (FILTER) that a valid, owned category with zero Expenses in the
# requested range still returns exactly one category, with all-zero buckets.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if one category with zero-value buckets returns.
def test_category_trend_endpoint_owned_category_filter_zero_activity(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    food = create_category(client=client, user_id=user_id, name="Food")

    # Act
    response = client.get(
        f"/api/v1/analytics/category-trend?period=month&count=3&category_id={food['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["categories"]) == 1
    item = body["categories"][0]
    assert len(item["buckets"]) == 3
    assert all(b["total_spent"] == "0.00" for b in item["buckets"])


# Tests (FILTER) that another user's category cannot be selected - the
# request is rejected with the same not-found convention as a nonexistent
# category, never revealing that the category exists for someone else.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 404.
def test_category_trend_endpoint_other_users_category_rejected(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    other_users_category = create_category(client=client, user_id=other_user_id, name="Private")

    # Act
    response = client.get(
        f"/api/v1/analytics/category-trend?period=month&count=1&category_id={other_users_category['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404


# Tests (FILTER) that a nonexistent category_id is rejected the same way
# as an unowned one.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 404.
def test_category_trend_endpoint_nonexistent_category_rejected(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        f"/api/v1/analytics/category-trend?period=month&count=1&category_id={uuid4()}",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    assert response.status_code == 404


# Tests (BUCKETS) that empty periods are emitted as zero buckets per
# category, and that day/week/month granularities all work end to end.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the week bucket for a category runs Monday-Sunday.
def test_category_trend_endpoint_week_bucket_boundaries(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    week_start, week_end = week_bounds(today)
    food = create_category(client=client, user_id=user_id, name="Food")
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=15, category_id=food["id"],
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=week&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    bucket = response.json()["categories"][0]["buckets"][-1]
    assert bucket["period_start"] == week_start.isoformat()
    assert bucket["period_end"] == week_end.isoformat()
    assert Decimal(bucket["total_spent"]) == Decimal("15.00")


# Tests (BUCKETS) that the current bucket is incomplete and a future-dated
# Expense in that category does not leak into its total.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if is_complete is false and the future Expense
#   is excluded.
def test_category_trend_endpoint_current_bucket_incomplete_future_excluded(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    _, month_end = month_bounds(today)
    food = create_category(client=client, user_id=user_id, name="Food")
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=20, category_id=food["id"],
    )
    if today < month_end:
        future_date = today + timedelta(days=1)
        create_expense_with(
            client=client, user_id=user_id, expense_date=future_date.isoformat(), amount=999,
            category_id=food["id"],
        )

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    bucket = response.json()["categories"][0]["buckets"][-1]
    assert bucket["is_complete"] is False
    assert bucket["effective_end"] == today.isoformat()
    assert Decimal(bucket["total_spent"]) == Decimal("20.00")


# Tests (COMPARISON) that period_over_period uses the two most recent
# complete buckets for that category, never the current partial one.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the comparison reflects the two completed
#   months, not the current one.
def test_category_trend_endpoint_period_over_period(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, _ = month_bounds(today)
    last_month_end = month_start - timedelta(days=1)
    last_month_start, _ = month_bounds(last_month_end)
    two_months_ago_end = last_month_start - timedelta(days=1)
    food = create_category(client=client, user_id=user_id, name="Food")

    create_expense_with(
        client=client, user_id=user_id, expense_date=two_months_ago_end.isoformat(), amount=100,
        category_id=food["id"],
    )
    create_expense_with(
        client=client, user_id=user_id, expense_date=last_month_end.isoformat(), amount=150,
        category_id=food["id"],
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=3",
        headers=auth_headers(user_id),
    )

    # Assert
    comparison = response.json()["categories"][0]["period_over_period"]
    assert comparison is not None
    assert Decimal(comparison["previous_total_spent"]) == Decimal("100.00")
    assert Decimal(comparison["current_total_spent"]) == Decimal("150.00")
    assert comparison["direction"] == "up"


# Tests (CATEGORY DELETE SEMANTICS) that an Expense whose category was
# later deleted appears under Uncategorized, never under a recovered
# historical category name - Expense.category_id is set NULL by the FK,
# and VF-015C does not attempt to recover the deleted name.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the Expense's total appears under Uncategorized.
def test_category_trend_endpoint_deleted_category_becomes_uncategorized(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    category = create_category(client=client, user_id=user_id, name="Temporary")
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=30, category_id=category["id"],
    )

    delete_response = client.delete(
        f"/api/v1/categories/{category['id']}",
        headers=auth_headers(user_id),
    )
    assert delete_response.status_code == 204, delete_response.text

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert len(body["categories"]) == 1
    assert body["categories"][0]["category_id"] is None
    assert body["categories"][0]["category_name"] == "Uncategorized"
    assert Decimal(body["categories"][0]["buckets"][0]["total_spent"]) == Decimal("30.00")


# Tests (SECURITY) that category-trend Expenses and category names are
# scoped to the authenticated user only.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if another user's category/Expenses never appear.
def test_category_trend_endpoint_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    today = date.today()
    other_category = create_category(client=client, user_id=other_user_id, name="Private food")
    create_expense_with(
        client=client, user_id=other_user_id, expense_date=today.isoformat(), amount=500,
        category_id=other_category["id"],
    )

    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.json()["categories"] == []


# Tests (NETWORK) that no FX provider is ever called while serving a
# category-trend request.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if httpx.get is not called during the request.
def test_category_trend_endpoint_never_calls_fx_providers(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())
    food = create_category(client=client, user_id=user_id, name="Food")

    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), currency="USD", amount=100,
        category_id=food["id"],
    )
    ecb_mock.reset_mock()

    # Act
    client.get("/api/v1/analytics/category-trend?period=month&count=3", headers=auth_headers(user_id))

    # Assert
    ecb_mock.assert_not_called()


# Tests (ZERO DATA) that no category_id filter and no matching Expenses
# returns an empty categories list.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if categories == [].
def test_category_trend_endpoint_zero_data_returns_empty_categories(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        "/api/v1/analytics/category-trend?period=month&count=1",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["categories"] == []


# Tests (VALIDATION) that an unsupported period, a count below 1, and a
# count above the per-period maximum are all rejected, matching
# spending-trend's exact validation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if all three cases return 422.
def test_category_trend_endpoint_validation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act / Assert
    assert client.get(
        "/api/v1/analytics/category-trend?period=year&count=3", headers=auth_headers(user_id),
    ).status_code == 422
    assert client.get(
        "/api/v1/analytics/category-trend?period=month&count=0", headers=auth_headers(user_id),
    ).status_code == 422
    assert client.get(
        "/api/v1/analytics/category-trend?period=month&count=25", headers=auth_headers(user_id),
    ).status_code == 422


# ---------------------------------------------------------------------------
# VF-015D deterministic current-month spending forecast
# ---------------------------------------------------------------------------


# Tests (API) that the endpoint requires no query parameters at all - a
# bare GET with no query string succeeds.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the bare request returns 200.
def test_spending_forecast_endpoint_accepts_no_query_params(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    assert response.status_code == 200, response.text


# Tests (API) the full response contract: method/forecast_status literals,
# current-month window, and Decimal-as-string serialization.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every contract field matches.
def test_spending_forecast_endpoint_response_contract(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)
    days_in_month = (month_end - month_start).days + 1
    days_elapsed = (today - month_start).days + 1

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=100)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert body["method"] == "linear_run_rate"
    assert body["forecast_status"] == "available"
    assert body["period_start"] == month_start.isoformat()
    assert body["period_end"] == month_end.isoformat()
    assert body["as_of"] == today.isoformat()
    assert body["days_in_month"] == days_in_month
    assert body["days_elapsed"] == days_elapsed
    assert isinstance(body["spent_to_date"], str)
    assert Decimal(body["spent_to_date"]) == Decimal("100.00")
    assert body["expenses_count"] == 1
    assert body["unresolved_expenses_count"] == 0
    assert isinstance(body["average_daily_spending"], str)
    assert isinstance(body["projected_spending"], str)


# Tests (FX) that base-currency (EUR) and USD-original resolved Expenses
# are both summed via persisted base_amount - the same worked example as
# B5D/Spending Trend (100 EUR + 100 USD/84.73 EUR-base -> 184.73).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if spent_to_date == 184.73, not 200.
def test_spending_forecast_endpoint_sums_base_amount_across_currencies(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), currency="EUR", amount=100)
    usd_expense = create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), currency="USD", amount=100,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert Decimal(body["spent_to_date"]) == Decimal("100.00") + Decimal(usd_expense["base_amount"])
    assert body["spent_to_date"] != "200.00"


# Tests (DATA) that a previous-month Expense and a future-dated Expense
# within the current month are both excluded from spent_to_date, while a
# current-day Expense is included.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the current-day Expense counts.
def test_spending_forecast_endpoint_excludes_previous_month_and_future(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)
    previous_month_day = month_start - timedelta(days=1)

    create_expense_with(client=client, user_id=user_id, expense_date=previous_month_day.isoformat(), amount=999)
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=20)
    if today < month_end:
        future_date = today + timedelta(days=1)
        create_expense_with(client=client, user_id=user_id, expense_date=future_date.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(user_id),
    )

    # Assert
    assert Decimal(response.json()["spent_to_date"]) == Decimal("20.00")


# Tests (FX) that a legacy unresolved Expense in the current month makes
# the forecast unavailable, with both forecast figures null.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if forecast_status is "incomplete_data" and both
#   forecast figures are null.
def test_spending_forecast_endpoint_unresolved_legacy_expense_makes_incomplete(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    user_id = str(user_id_uuid)
    today = date.today()

    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=None,
        title="Legacy USD",
        amount=Decimal("999.00"),
        currency="USD",
        expense_date=today,
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    db_session.close()

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=50)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(user_id),
    )

    # Assert
    body = response.json()
    assert body["forecast_status"] == "incomplete_data"
    assert Decimal(body["spent_to_date"]) == Decimal("50.00")
    assert body["expenses_count"] == 1
    assert body["unresolved_expenses_count"] == 1
    assert body["average_daily_spending"] is None
    assert body["projected_spending"] is None


# Tests (ZERO DATA) that a brand-new user still receives a valid,
# "available" forecast of zero.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if every figure reflects the zero-data state.
def test_spending_forecast_endpoint_zero_data_new_user(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(str(uuid4())),
    )

    # Assert
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert body["forecast_status"] == "available"
    assert body["spent_to_date"] == "0.00"
    assert body["expenses_count"] == 0
    assert body["unresolved_expenses_count"] == 0
    assert body["average_daily_spending"] == "0.00"
    assert body["projected_spending"] == "0.00"


# Tests (SECURITY) that spending-forecast is scoped to the authenticated
# user only.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if another user's Expense never affects the total.
def test_spending_forecast_endpoint_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    today = date.today()
    create_expense_with(client=client, user_id=other_user_id, expense_date=today.isoformat(), amount=500)

    # Act
    response = client.get(
        "/api/v1/analytics/spending-forecast",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.json()["spent_to_date"] == "0.00"


# Tests (NETWORK) that no FX provider is ever called while serving a
# spending-forecast request.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if httpx.get is not called during the request.
def test_spending_forecast_endpoint_never_calls_fx_providers(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1803, actual_date=today.isoformat())

    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), currency="USD", amount=100)
    ecb_mock.reset_mock()

    # Act
    client.get("/api/v1/analytics/spending-forecast", headers=auth_headers(user_id))

    # Assert
    ecb_mock.assert_not_called()


# Tests (REGRESSION) that spending-trend, category-trend, monthly-summary,
# and budget-status all still work unchanged after adding spending-forecast.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if all four endpoints return 200 with a real Expense.
def test_spending_forecast_addition_does_not_affect_other_analytics_endpoints(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=25)

    # Act / Assert
    assert client.get(
        "/api/v1/analytics/spending-trend?period=month&count=1", headers=auth_headers(user_id),
    ).status_code == 200
    assert client.get(
        "/api/v1/analytics/category-trend?period=month&count=1", headers=auth_headers(user_id),
    ).status_code == 200
    assert client.get(
        f"/api/v1/analytics/monthly-summary?year={today.year}&month={today.month}",
        headers=auth_headers(user_id),
    ).status_code == 200
    assert client.get(
        "/api/v1/analytics/budget-status", headers=auth_headers(user_id),
    ).status_code == 200


# Tests that the budget status endpoint returns exceeded budget information,
# calculated against the real current calendar month (no public as_of -
# the endpoint always uses the server's today).
# This test exists to verify budget analytics calculations through the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if exceeded budget information is returned correctly.
def test_budget_status_endpoint_returns_budget_status(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )
    category_id = category["id"]

    create_expense_with(
        client=client,
        user_id=user_id,
        expense_date=today.isoformat(),
        category_id=category_id,
        amount=120,
    )

    create_budget_with(
        client=client,
        user_id=user_id,
        start_date=date(2020, 1, 1).isoformat(),
        period="monthly",
        category_id=category_id,
        name="Food budget",
        limit_amount=100,
    )

    # Act - no as_of: the endpoint always uses the server's current date.
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["budget_name"] == "Food budget"
    assert response_data[0]["category_id"] == category_id
    assert response_data[0]["category_name"] == "Food"
    assert response_data[0]["period"] == "monthly"
    assert response_data[0]["period_start"] == month_start.isoformat()
    assert response_data[0]["period_end"] == month_end.isoformat()
    assert response_data[0]["period_state"] == "active"
    assert response_data[0]["limit_amount"] == "100.00"
    assert response_data[0]["spent"] == "120.00"
    assert response_data[0]["remaining"] in ["0", "0.00"]
    assert response_data[0]["exceeded_amount"] == "20.00"
    assert response_data[0]["utilization_percent"] == "120.00"
    assert response_data[0]["is_exceeded"] is True


# Tests (A) that a monthly budget only counts expenses in the current
# calendar month, excluding a prior-month expense.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the current-month expense counts.
def test_budget_status_endpoint_monthly_counts_current_month_only(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)
    last_day_prev_month = month_start - timedelta(days=1)

    budget = create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Monthly budget", limit_amount=100,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=40)
    create_expense_with(client=client, user_id=user_id, expense_date=last_day_prev_month.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["budget_id"] == budget["id"]
    assert status["period_start"] == month_start.isoformat()
    assert status["period_end"] == month_end.isoformat()
    assert status["spent"] == "40.00"


# Tests (B) that a weekly budget only counts expenses in the current
# Monday-Sunday window.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the in-window expense counts.
def test_budget_status_endpoint_weekly_counts_current_week_only(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    week_start, week_end = week_bounds(today)
    prior_week_day = week_start - timedelta(days=1)

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="weekly",
        name="Weekly budget", limit_amount=50,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=10)
    create_expense_with(client=client, user_id=user_id, expense_date=prior_week_day.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["period_start"] == week_start.isoformat()
    assert status["period_end"] == week_end.isoformat()
    assert status["spent"] == "10.00"


# Tests (C) that a yearly budget only counts expenses in the current
# calendar year.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the current-year expense counts.
def test_budget_status_endpoint_yearly_counts_current_year_only(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    last_day_prev_year = date(today.year - 1, 12, 31)

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2010, 1, 1).isoformat(), period="yearly",
        name="Yearly budget", limit_amount=1000,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=30)
    create_expense_with(client=client, user_id=user_id, expense_date=last_day_prev_year.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["period_start"] == date(today.year, 1, 1).isoformat()
    assert status["period_end"] == date(today.year, 12, 31).isoformat()
    assert status["spent"] == "30.00"


# Tests (D) that a budget created mid-period only counts expenses from its
# start_date onward, and (F) that a future-dated expense does not count.
# This test anchors the budget's start_date at today itself: whatever day
# of the month today happens to be, "yesterday" is guaranteed outside the
# activation window (whether same month or the previous one) and
# "tomorrow" is guaranteed future-dated - both exclusions hold without
# depending on today falling mid-month.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the on-activation-date expense counts.
def test_budget_status_endpoint_mid_period_start_and_future_expense_excluded(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    create_budget_with(
        client=client, user_id=user_id, start_date=today.isoformat(), period="monthly",
        name="Mid-period budget", limit_amount=100,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=yesterday.isoformat(), amount=999)  # before activation
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=30)  # counts
    create_expense_with(client=client, user_id=user_id, expense_date=tomorrow.isoformat(), amount=999)  # future

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["effective_start"] == today.isoformat()
    assert status["spent"] == "30.00"


# Tests (E) that a budget ending mid-period only counts expenses through
# end_date, and reports its final effective period rather than its entire
# historical lifetime.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only pre-end_date spending in the final
#   period counts.
def test_budget_status_endpoint_mid_period_end_uses_final_period(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    end_date = date.today() - timedelta(days=90)  # ended well in the past
    final_period_start, _ = month_bounds(end_date)
    day_after_end = end_date + timedelta(days=1)

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2010, 1, 1).isoformat(), end_date=end_date.isoformat(),
        period="monthly", name="Ending budget", limit_amount=500,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=date(2010, 6, 1).isoformat(), amount=100)  # earlier lifetime
    create_expense_with(client=client, user_id=user_id, expense_date=final_period_start.isoformat(), amount=100)  # in final period
    create_expense_with(client=client, user_id=user_id, expense_date=end_date.isoformat(), amount=40)  # exact end_date
    create_expense_with(client=client, user_id=user_id, expense_date=day_after_end.isoformat(), amount=999)  # after end_date

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["period_state"] == "ended"
    assert status["period_start"] == final_period_start.isoformat()
    assert status["effective_end"] == end_date.isoformat()
    assert status["spent"] == "140.00"


# Tests (G) that editing a budget's limit is reflected in the current
# period's status through the public endpoint.
# Verifying (H) - that a past period still resolves the original
# configuration - requires an arbitrary-date query, which is no longer
# part of the public contract; that half of this scenario is instead
# covered at the service level directly in
# tests/unit/analytics/test_analytics_service.py, using the internal
# as_of parameter the task explicitly keeps for testability.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the current-period query reflects the new limit.
def test_budget_status_endpoint_edit_uses_current_version(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    budget = create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=500,
    )

    patch_response = client.patch(
        f"/api/v1/budgets/{budget['id']}",
        json={"limit_amount": 600},
        headers=auth_headers(user_id),
    )
    assert patch_response.status_code == 200, patch_response.text

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.json()[0]["limit_amount"] == "600.00"


# Tests (I) that a budget's category scope comes from the BudgetVersion
# resolved for the current period, reflecting a category edit made today.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the new category's expenses count after
#   the edit.
def test_budget_status_endpoint_category_edit_uses_resolved_version_scope(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    original_category = create_category(client=client, user_id=user_id, name="Food")
    new_category = create_category(client=client, user_id=user_id, name="Dining out")

    budget = create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=100, category_id=original_category["id"],
    )
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=20,
        category_id=original_category["id"],
    )
    create_expense_with(
        client=client, user_id=user_id, expense_date=today.isoformat(), amount=15,
        category_id=new_category["id"],
    )

    patch_response = client.patch(
        f"/api/v1/budgets/{budget['id']}",
        json={"category_id": new_category["id"]},
        headers=auth_headers(user_id),
    )
    assert patch_response.status_code == 200, patch_response.text

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["category_id"] == new_category["id"]
    assert status["category_name"] == "Dining out"
    assert status["spent"] == "15.00"


# Tests (J) that budget status is scoped to the authenticated user only.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the other user's budget never appears.
def test_budget_status_endpoint_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_budget_with(
        client=client, user_id=other_user_id, start_date=date(2020, 1, 1).isoformat(),
        name="Other user's budget",
    )

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == []


# Tests (K) same-currency arithmetic correctness and (L) that a
# mismatched-currency expense is never summed into spent.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only the EUR expense counts toward the EUR budget.
def test_budget_status_endpoint_currency_mismatch_excluded(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="EUR budget", limit_amount=100, currency="EUR",
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=20, currency="EUR")
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=999, currency="USD")

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.json()[0]["spent"] == "20.00"


# ---------------------------------------------------------------------------
# VF-014B4 smart budget metrics (days/pace/projection/risk_status)
# ---------------------------------------------------------------------------


# Tests (A) that an active monthly budget's response includes every VF-014B4
# field with plausible values.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if all B4 fields are present and well-typed.
def test_budget_status_endpoint_includes_all_b4_fields(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=300,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=50)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    for field in (
        "days_in_period", "days_elapsed", "days_remaining",
        "average_daily_spending", "daily_spending_allowance",
        "projected_spending", "projected_surplus", "projected_deficit",
        "risk_status",
    ):
        assert field in status, field
    assert status["risk_status"] in ("healthy", "watch", "at_risk", "exceeded")


# Tests (B) that daily_spending_allowance is correctly computed against the
# real current-month remaining effective days.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the allowance matches an independently
#   computed remaining/days_remaining value.
def test_budget_status_endpoint_daily_allowance_matches_remaining_days(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)
    days_in_period = (month_end - month_start).days + 1
    days_elapsed = (today - month_start).days + 1
    days_remaining = days_in_period - days_elapsed + 1

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=300,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=90)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    expected_allowance = (
        (Decimal("300") - Decimal("90")) / days_remaining
    ).quantize(Decimal("0.01"))
    assert status["days_remaining"] == days_remaining
    assert status["daily_spending_allowance"] == str(expected_allowance)


# Tests (C) that projected_spending matches the current-pace linear
# projection formula against the real current month.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if projected_spending matches an independently
#   computed pace projection.
def test_budget_status_endpoint_projected_spending_matches_pace_formula(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    month_start, month_end = month_bounds(today)
    days_in_period = (month_end - month_start).days + 1
    days_elapsed = (today - month_start).days + 1

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=1000,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=60)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    expected_projection = (
        (Decimal("60") / days_elapsed) * days_in_period
    ).quantize(Decimal("0.01"))
    assert response.json()[0]["projected_spending"] == str(expected_projection)


# Tests (D) that a spending pace above the limit produces a nonzero
# projected_deficit and zero projected_surplus.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if deficit is nonzero and surplus is zero.
def test_budget_status_endpoint_projected_deficit_when_pace_exceeds_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Overspending", limit_amount=100,
    )
    # spent is just under the limit (not yet actually exceeded - that case
    # is F below), but the pace projection multiplies it out over the rest
    # of the month, which pushes the projection over the limit on every day
    # of the month except the very last one (where days_in_period ==
    # days_elapsed and the projection multiplier is exactly 1).
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=99)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["is_exceeded"] is False
    assert Decimal(status["projected_deficit"]) > Decimal("0")
    assert Decimal(status["projected_surplus"]) == Decimal("0.00")
    assert status["risk_status"] == "at_risk"


# Tests (E) that a spending pace comfortably below the limit produces a
# nonzero projected_surplus and zero projected_deficit.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if surplus is nonzero and deficit is zero.
def test_budget_status_endpoint_projected_surplus_when_pace_below_budget(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Underspending", limit_amount=100000,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=1)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert Decimal(status["projected_surplus"]) > Decimal("0")
    assert Decimal(status["projected_deficit"]) == Decimal("0.00")
    assert status["risk_status"] == "healthy"


# Tests (F) that an already-exceeded budget reports zero daily allowance
# and exceeded risk_status through the full API, regardless of pace.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if allowance is zero and risk_status is exceeded.
def test_budget_status_endpoint_exceeded_budget_zero_allowance_exceeded_risk(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Exceeded", limit_amount=50,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=200)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["is_exceeded"] is True
    assert status["daily_spending_allowance"] == "0.00"
    assert status["risk_status"] == "exceeded"


# Tests (G) that a future-dated expense does not influence average daily
# spending or the pace projection.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if metrics are computed as if the future expense
#   did not exist.
def test_budget_status_endpoint_future_expense_does_not_affect_metrics(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()
    tomorrow = today + timedelta(days=1)

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=1000,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=10)
    create_expense_with(client=client, user_id=user_id, expense_date=tomorrow.isoformat(), amount=99999)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["risk_status"] == "healthy"
    assert Decimal(status["average_daily_spending"]) < Decimal("100")


# Tests (H) that a mismatched-currency expense does not influence average
# daily spending or the pace projection.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if metrics ignore the foreign-currency expense.
def test_budget_status_endpoint_mixed_currency_expense_does_not_affect_metrics(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="EUR budget", limit_amount=1000, currency="EUR",
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=10, currency="EUR")
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=99999, currency="USD")

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["risk_status"] == "healthy"
    assert Decimal(status["average_daily_spending"]) < Decimal("100")


# Tests (I) that a partial-period budget's B4 metrics use the effective
# (partial) period length rather than the full calendar month.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if days_in_period equals today-to-month-end, not
#   the full month.
def test_budget_status_endpoint_partial_period_metrics_use_effective_length(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange - budget activates today; effective window is today..month_end
    user_id = str(uuid4())
    today = date.today()
    _, month_end = month_bounds(today)
    expected_days_in_period = (month_end - today).days + 1

    create_budget_with(
        client=client, user_id=user_id, start_date=today.isoformat(), period="monthly",
        name="Mid-period", limit_amount=300,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=30)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    status = response.json()[0]
    assert status["days_in_period"] == expected_days_in_period
    assert status["days_elapsed"] == 1


# Tests (J) that editing a budget's limit changes the projection/risk
# computed for the current period, proving the resolved BudgetVersion
# (not a stale value) drives B4 metrics.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if risk_status/projected_surplus reflect the
#   edited limit.
def test_budget_status_endpoint_version_limit_drives_projection_and_risk(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    today = date.today()

    budget = create_budget_with(
        client=client, user_id=user_id, start_date=date(2020, 1, 1).isoformat(), period="monthly",
        name="Groceries", limit_amount=10,
    )
    create_expense_with(client=client, user_id=user_id, expense_date=today.isoformat(), amount=5)

    before_response = client.get("/api/v1/analytics/budget-status", headers=auth_headers(user_id))
    before_status = before_response.json()[0]

    # Act - raise the limit enough to flip risk_status from at_risk/watch to healthy
    patch_response = client.patch(
        f"/api/v1/budgets/{budget['id']}",
        json={"limit_amount": 100000},
        headers=auth_headers(user_id),
    )
    assert patch_response.status_code == 200, patch_response.text

    after_response = client.get("/api/v1/analytics/budget-status", headers=auth_headers(user_id))
    after_status = after_response.json()[0]

    # Assert
    assert after_status["limit_amount"] == "100000.00"
    assert Decimal(after_status["projected_surplus"]) > Decimal(before_status["projected_surplus"])
    assert after_status["risk_status"] == "healthy"


# Tests (K) that B4 metrics fields, like the rest of the response, are
# scoped to the authenticated user only.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the other user's budget (and its metrics)
#   never appear.
def test_budget_status_endpoint_metrics_ownership_isolation(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    today = date.today()

    create_budget_with(
        client=client, user_id=other_user_id, start_date=date(2020, 1, 1).isoformat(),
        name="Other user's budget", limit_amount=50,
    )
    create_expense_with(client=client, user_id=other_user_id, expense_date=today.isoformat(), amount=999)

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == []


# Tests that the goal progress endpoint returns remaining goal amount.
# This test exists to verify financial goal analytics through the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if remaining goal amount is returned correctly.
def test_goal_progress_endpoint_returns_goal_progress(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    create_goal(
        client=client,
        user_id=user_id,
        name="Vacation",
        target_amount=2000,
        current_amount=500,
    )

    # Act
    response = client.get(
        "/api/v1/analytics/goal-progress",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["name"] == "Vacation"
    assert response_data[0]["target_amount"] == "2000.00"
    assert response_data[0]["current_amount"] == "500.00"
    assert response_data[0]["remaining_amount"] == "1500.00"
    assert response_data[0]["progress_percent"] == "25.00"
    assert response_data[0]["status"] == "active"
    assert response_data[0]["target_date"] == "2026-12-31"


# Tests that analytics endpoints reject requests without authentication header.
# This test exists to verify that the temporary auth dependency protects analytics data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_monthly_summary_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/analytics/monthly-summary")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."