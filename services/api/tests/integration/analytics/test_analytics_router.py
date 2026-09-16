from datetime import date, timedelta
from typing import Any, Optional
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import (
    auth_headers,
    create_budget,
    create_category,
    create_expense,
    create_goal,
)


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