from uuid import uuid4

from fastapi.testclient import TestClient


# Tests that the monthly summary endpoint returns total spending data.
# This test exists to verify that analytics monthly summary is exposed through the API.
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

    expense_response = client.post(
        "/api/v1/expenses",
        headers={"X-User-Id": user_id},
        json={
            "category_id": None,
            "title": "Groceries",
            "amount": 50,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": "Groceries",
            "source": "manual",
        },
    )

    assert expense_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/analytics/monthly-summary",
        params={"user_id": user_id},
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["total_spent"] == "50.00"
    assert response_data["expenses_count"] == 1


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

    category_response = client.post(
        "/api/v1/categories",
        headers={"X-User-Id": user_id},
        json={
            "name": "Food",
            "color": "#FF5733",
            "icon": "utensils",
        },
    )

    assert category_response.status_code == 201

    category_id = category_response.json()["id"]

    first_expense_response = client.post(
        "/api/v1/expenses",
        headers={"X-User-Id": user_id},
        json={
            "category_id": category_id,
            "title": "Groceries",
            "amount": 20,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": "Groceries",
            "source": "manual",
        },
    )

    second_expense_response = client.post(
        "/api/v1/expenses",
        headers={"X-User-Id": user_id},
        json={
            "category_id": category_id,
            "title": "Dinner",
            "amount": 30,
            "currency": "EUR",
            "expense_date": "2026-05-08",
            "description": "Dinner",
            "source": "manual",
        },
    )

    assert first_expense_response.status_code == 201
    assert second_expense_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/analytics/category-summary",
        params={"user_id": user_id},
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["category_id"] == category_id
    assert response_data[0]["category_name"] == "Food"
    assert response_data[0]["total_spent"] == "50.00"
    assert response_data[0]["expenses_count"] == 2


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

    category_response = client.post(
        "/api/v1/categories",
        headers={"X-User-Id": user_id},
        json={
            "name": "Food",
            "color": "#FF5733",
            "icon": "utensils",
        },
    )

    assert category_response.status_code == 201

    category_id = category_response.json()["id"]

    expense_response = client.post(
        "/api/v1/expenses",
        headers={"X-User-Id": user_id},
        json={
            "category_id": category_id,
            "title": "Groceries",
            "amount": 120,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": "Groceries",
            "source": "manual",
        },
    )

    assert expense_response.status_code == 201

    budget_response = client.post(
        "/api/v1/budgets",
        headers={"X-User-Id": user_id},
        json={
            "category_id": category_id,
            "name": "Food budget",
            "limit_amount": 100,
            "currency": "EUR",
            "period": "monthly",
            "start_date": "2026-05-01",
            "end_date": None,
        },
    )

    assert budget_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/analytics/budget-status",
        params={"user_id": user_id},
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

    goal_response = client.post(
        "/api/v1/goals",
        headers={"X-User-Id": user_id},
        json={
            "name": "Vacation",
            "target_amount": 2000,
            "current_amount": 500,
            "currency": "EUR",
            "target_date": "2026-12-31",
            "status": "active",
        },
    )

    assert goal_response.status_code == 201

    # Act
    response = client.get(
        "/api/v1/analytics/goal-progress",
        params={"user_id": user_id},
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