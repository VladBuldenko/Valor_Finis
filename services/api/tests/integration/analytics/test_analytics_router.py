from fastapi.testclient import TestClient

from app.main import app
from app.modules.budgets import budget_repository as budgets_repository
from app.modules.expenses import expenses_repository as expenses_repository
from app.modules.goals import goal_repository as goals_repository


client = TestClient(app)


# Resets all in-memory repositories before each analytics integration test.
# This helper exists to keep API tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    expenses_repository.expenses_storage.clear()
    expenses_repository.next_expense_id = 1

    budgets_repository.budgets_storage.clear()
    budgets_repository.next_budget_id = 1

    goals_repository.goals_storage.clear()
    goals_repository.next_goal_id = 1


# Tests that the monthly summary endpoint returns total spending data.
# This test exists to verify that analytics monthly summary is exposed through the API.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the API returns correct monthly summary values.
def test_monthly_summary_endpoint_returns_summary() -> None:
    # Arrange
    reset_repository_state()

    client.post(
        "/api/v1/expenses",
        json={
            "amount": 50,
            "category": "food",
            "description": "Groceries",
            "date": "2026-05-07",
        },
    )

    # Act
    response = client.get("/api/v1/analytics/monthly-summary")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data["total_spent"] == "50"
    assert response_data["expenses_count"] == 1


# Tests that the category summary endpoint groups expenses by category.
# This test exists to verify category analytics API calculations.
# Parameters:
# - None.
# Returns:
# - None. The test passes if grouped category totals are returned correctly.
def test_category_summary_endpoint_returns_grouped_categories() -> None:
    # Arrange
    reset_repository_state()

    client.post(
        "/api/v1/expenses",
        json={
            "amount": 20,
            "category": "food",
            "description": "Groceries",
            "date": "2026-05-07",
        },
    )

    client.post(
        "/api/v1/expenses",
        json={
            "amount": 30,
            "category": "food",
            "description": "Dinner",
            "date": "2026-05-08",
        },
    )

    # Act
    response = client.get("/api/v1/analytics/category-summary")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["category"] == "food"
    assert response_data[0]["total_spent"] == "50"


# Tests that the budget status endpoint returns exceeded budget information.
# This test exists to verify budget analytics calculations through the API.
# Parameters:
# - None.
# Returns:
# - None. The test passes if exceeded budget information is returned correctly.
def test_budget_status_endpoint_returns_budget_status() -> None:
    # Arrange
    reset_repository_state()

    client.post(
        "/api/v1/expenses",
        json={
            "amount": 120,
            "category": "food",
            "description": "Groceries",
            "date": "2026-05-07",
        },
    )

    client.post(
        "/api/v1/budgets",
        json={
            "category": "food",
            "monthly_limit": 100,
            "month": "2026-05-01",
        },
    )

    # Act
    response = client.get("/api/v1/analytics/budget-status")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data[0]["category"] == "food"
    assert response_data[0]["spent"] == "120"
    assert response_data[0]["remaining"] == "0"
    assert response_data[0]["exceeded_amount"] == "20"
    assert response_data[0]["is_exceeded"] is True


# Tests that the goal progress endpoint returns remaining goal amount.
# This test exists to verify financial goal analytics through the API.
# Parameters:
# - None.
# Returns:
# - None. The test passes if remaining goal amount is returned correctly.
def test_goal_progress_endpoint_returns_goal_progress() -> None:
    # Arrange
    reset_repository_state()

    client.post(
        "/api/v1/goals",
        json={
            "name": "Vacation",
            "target_amount": 2000,
            "current_amount": 500,
            "deadline": "2026-12-31",
        },
    )

    # Act
    response = client.get("/api/v1/analytics/goal-progress")

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert response_data[0]["name"] == "Vacation"
    assert response_data[0]["remaining_amount"] == "1500"