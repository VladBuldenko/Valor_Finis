from datetime import date
from decimal import Decimal

from app.modules.analytics import analytics_service
from app.modules.budgets import budget_repository as budgets_repository
from app.modules.budgets.budget_schemas import BudgetCreate
from app.modules.expenses import expenses_repository as expenses_repository
from app.modules.expenses.expenses_schemas import ExpenseCreate
from app.modules.goals import goal_repository as goals_repository
from app.modules.goals.goal_schemas import GoalCreate


# Resets all in-memory repositories before each analytics test.
# This helper exists to keep analytics tests independent from each other.
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


# Tests that monthly summary calculates total spent and expense count.
# This test exists to verify the main dashboard spending summary.
# Parameters:
# - None.
# Returns:
# - None. The test passes if total spending and count are calculated correctly.
def test_get_monthly_summary_calculates_total_spent_and_count() -> None:
    # Arrange
    reset_repository_state()

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("24.99"),
            category="food",
            description="Groceries",
            date=date(2026, 5, 7),
        )
    )

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("10.01"),
            category="cafe",
            description="Coffee",
            date=date(2026, 5, 8),
        )
    )

    # Act
    summary = analytics_service.get_monthly_summary()

    # Assert
    assert summary.total_spent == Decimal("35.00")
    assert summary.expenses_count == 2


# Tests that category summary groups expenses by category.
# This test exists to verify that the dashboard can show where money was spent.
# Parameters:
# - None.
# Returns:
# - None. The test passes if category totals are calculated correctly.
def test_get_category_summary_groups_expenses_by_category() -> None:
    # Arrange
    reset_repository_state()

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("20"),
            category="food",
            description="Groceries",
            date=date(2026, 5, 7),
        )
    )

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("30"),
            category="food",
            description="More groceries",
            date=date(2026, 5, 8),
        )
    )

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("15"),
            category="cafe",
            description="Coffee",
            date=date(2026, 5, 9),
        )
    )

    # Act
    category_summary = analytics_service.get_category_summary()
    totals_by_category = {
        item.category: item.total_spent for item in category_summary
    }

    # Assert
    assert totals_by_category["food"] == Decimal("50")
    assert totals_by_category["cafe"] == Decimal("15")


# Tests that budget status calculates remaining budget when spending is below the limit.
# This test exists to verify that users can see how much budget is still available.
# Parameters:
# - None.
# Returns:
# - None. The test passes if remaining budget is calculated correctly.
def test_get_budget_status_calculates_remaining_budget() -> None:
    # Arrange
    reset_repository_state()

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("75"),
            category="food",
            description="Groceries",
            date=date(2026, 5, 7),
        )
    )

    budgets_repository.create_budget(
        BudgetCreate(
            category="food",
            monthly_limit=Decimal("100"),
            month=date(2026, 5, 1),
        )
    )

    # Act
    budget_status = analytics_service.get_budget_status()
    food_status = budget_status[0]

    # Assert
    assert food_status.category == "food"
    assert food_status.monthly_limit == Decimal("100")
    assert food_status.spent == Decimal("75")
    assert food_status.remaining == Decimal("25")
    assert food_status.exceeded_amount == Decimal("0")
    assert food_status.is_exceeded is False


# Tests that budget status calculates exceeded amount when spending is above the limit.
# This test exists to verify that users can detect overspending.
# Parameters:
# - None.
# Returns:
# - None. The test passes if exceeded amount is calculated correctly.
def test_get_budget_status_calculates_exceeded_amount() -> None:
    # Arrange
    reset_repository_state()

    expenses_repository.create_expense(
        ExpenseCreate(
            amount=Decimal("120"),
            category="food",
            description="Groceries",
            date=date(2026, 5, 7),
        )
    )

    budgets_repository.create_budget(
        BudgetCreate(
            category="food",
            monthly_limit=Decimal("100"),
            month=date(2026, 5, 1),
        )
    )

    # Act
    budget_status = analytics_service.get_budget_status()
    food_status = budget_status[0]

    # Assert
    assert food_status.category == "food"
    assert food_status.spent == Decimal("120")
    assert food_status.remaining == Decimal("0")
    assert food_status.exceeded_amount == Decimal("20")
    assert food_status.is_exceeded is True


# Tests that goal progress calculates remaining amount.
# This test exists to verify that users can see how much money is still needed for a goal.
# Parameters:
# - None.
# Returns:
# - None. The test passes if remaining goal amount is calculated correctly.
def test_get_goal_progress_calculates_remaining_amount() -> None:
    # Arrange
    reset_repository_state()

    goals_repository.create_goal(
        GoalCreate(
            name="Vacation",
            target_amount=Decimal("2000"),
            current_amount=Decimal("500"),
            deadline=date(2026, 12, 31),
        )
    )

    # Act
    goal_progress = analytics_service.get_goal_progress()
    vacation_goal = goal_progress[0]

    # Assert
    assert vacation_goal.name == "Vacation"
    assert vacation_goal.target_amount == Decimal("2000")
    assert vacation_goal.current_amount == Decimal("500")
    assert vacation_goal.remaining_amount == Decimal("1500")