from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import (
    auth_headers,
    create_budget,
    create_category,
    create_expense,
    create_goal,
)


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

# Tests that the budget status endpoint returns exceeded budget information.
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
        amount=120,
    )

    create_budget(
        client=client,
        user_id=user_id,
        category_id=category_id,
        name="Food budget",
        limit_amount=100,
    )

    # Act
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
    assert response_data[0]["limit_amount"] == "100.00"
    assert response_data[0]["spent"] == "120.00"
    assert response_data[0]["remaining"] in ["0", "0.00"]
    assert response_data[0]["exceeded_amount"] == "20.00"
    assert response_data[0]["is_exceeded"] is True


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