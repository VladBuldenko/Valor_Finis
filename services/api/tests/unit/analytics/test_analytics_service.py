from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from typing import cast
from sqlalchemy.orm import Session
from pytest import MonkeyPatch

from app.modules.analytics import analytics_service

# Creates a simple object with dynamic attributes.
# This helper exists to imitate SQLAlchemy models without using the database.
# Parameters:
# - kwargs: field names and values for the fake model.
# Returns:
# - SimpleNamespace object with provided attributes.
def make_model(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


# Tests that monthly summary calculates total spent and expense count.
# This test exists to verify dashboard summary business logic without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if total spending and count are calculated correctly.
def test_get_monthly_summary_calculates_total_spent_and_count(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()

    expenses = [
        make_model(
            amount=Decimal("24.99"),
            expense_date=date(2026, 5, 7),
        ),
        make_model(
            amount=Decimal("10.01"),
            expense_date=date(2026, 5, 8),
        ),
    ]

    def fake_get_expenses(
        db_session: Session,
        user_id: UUID,
    ):
        return expenses

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session,
        user_id=user_id,
        year=2026,
        month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("35.00")
    assert summary.expenses_count == 2

# Tests that category summary groups expenses by category and resolves category names.
# This test exists to verify category analytics business logic without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if category totals and names are calculated correctly.
def test_get_category_summary_groups_expenses_by_category(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    unknown_category_id = uuid4()

    categories = [
        make_model(id=food_category_id, name="Food"),
    ]

    expenses = [
        make_model(category_id=food_category_id, amount=Decimal("20.00")),
        make_model(category_id=food_category_id, amount=Decimal("30.00")),
        make_model(category_id=None, amount=Decimal("15.00")),
        make_model(category_id=unknown_category_id, amount=Decimal("5.00")),
    ]

    def fake_get_expenses(db_session: object, user_id=None):
        return expenses

    def fake_get_categories(db_session: object, user_id=None):
        return categories

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session,
        user_id=user_id,
    )
    summary_by_category_id = {
        item.category_id: item for item in category_summary
    }

    # Assert
    assert len(category_summary) == 3

    assert summary_by_category_id[food_category_id].category_name == "Food"
    assert summary_by_category_id[food_category_id].total_spent == Decimal("50.00")
    assert summary_by_category_id[food_category_id].expenses_count == 2

    assert summary_by_category_id[None].category_name == "Uncategorized"
    assert summary_by_category_id[None].total_spent == Decimal("15.00")
    assert summary_by_category_id[None].expenses_count == 1

    assert summary_by_category_id[unknown_category_id].category_name == "Uncategorized"
    assert summary_by_category_id[unknown_category_id].total_spent == Decimal("5.00")
    assert summary_by_category_id[unknown_category_id].expenses_count == 1

# Tests that category summary includes only expenses from the selected month.
# This test exists to verify monthly filtering for dashboard category analytics.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if expenses outside the selected month are excluded.
def test_get_category_summary_filters_by_selected_month(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()

    categories = [
        make_model(id=food_category_id, name="Food"),
    ]

    expenses = [
        make_model(
            category_id=food_category_id,
            amount=Decimal("20.00"),
            expense_date=date(2026, 5, 7),
        ),
        make_model(
            category_id=food_category_id,
            amount=Decimal("30.00"),
            expense_date=date(2026, 5, 20),
        ),
        make_model(
            category_id=food_category_id,
            amount=Decimal("70.00"),
            expense_date=date(2026, 6, 7),
        ),
    ]

    def fake_get_expenses(
        db_session: object,
        user_id=None,
    ):
        return expenses

    def fake_get_categories(
        db_session: object,
        user_id=None,
    ):
        return categories

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session,
        user_id=user_id,
        year=2026,
        month=5,
    )

    # Assert
    assert len(category_summary) == 1
    assert category_summary[0].category_id == food_category_id
    assert category_summary[0].category_name == "Food"
    assert category_summary[0].total_spent == Decimal("50.00")
    assert category_summary[0].expenses_count == 2

# Tests that budget status calculates spent, remaining, and exceeded amounts.
# This test exists to verify budget analytics business logic without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if budget status values are calculated correctly.
def test_get_budget_status_calculates_remaining_and_exceeded_amounts(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    transport_category_id = uuid4()

    food_budget_id = uuid4()
    general_budget_id = uuid4()

    categories = [
        make_model(id=food_category_id, name="Food"),
        make_model(id=transport_category_id, name="Transport"),
    ]

    expenses = [
        make_model(
            category_id=food_category_id,
            amount=Decimal("75.00"),
            expense_date=date(2026, 5, 7),
        ),
        make_model(
            category_id=food_category_id,
            amount=Decimal("25.00"),
            expense_date=date(2026, 4, 30),
        ),
        make_model(
            category_id=food_category_id,
            amount=Decimal("10.00"),
            expense_date=date(2026, 6, 1),
        ),
        make_model(
            category_id=transport_category_id,
            amount=Decimal("40.00"),
            expense_date=date(2026, 5, 10),
        ),
    ]

    budgets = [
        make_model(
            id=food_budget_id,
            name="Food budget",
            category_id=food_category_id,
            limit_amount=Decimal("100.00"),
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
        ),
        make_model(
            id=general_budget_id,
            name="General budget",
            category_id=None,
            limit_amount=Decimal("100.00"),
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
        ),
    ]

    def fake_get_expenses(db_session: object, user_id=None):
        return expenses

    def fake_get_budgets(db_session: object, user_id=None):
        return budgets

    def fake_get_categories(db_session: object, user_id=None):
        return categories

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )
    monkeypatch.setattr(
        analytics_service.budgets_repository,
        "get_budgets",
        fake_get_budgets,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_categories,
    )

    # Act
    budget_status = analytics_service.get_budget_status(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    food_status = budget_status[0]
    general_status = budget_status[1]

    assert food_status.budget_id == food_budget_id
    assert food_status.budget_name == "Food budget"
    assert food_status.category_id == food_category_id
    assert food_status.category_name == "Food"
    assert food_status.limit_amount == Decimal("100.00")
    assert food_status.spent == Decimal("75.00")
    assert food_status.remaining == Decimal("25.00")
    assert food_status.exceeded_amount == Decimal("0")
    assert food_status.is_exceeded is False

    assert general_status.budget_id == general_budget_id
    assert general_status.budget_name == "General budget"
    assert general_status.category_id is None
    assert general_status.category_name == "Uncategorized"
    assert general_status.limit_amount == Decimal("100.00")
    assert general_status.spent == Decimal("115.00")
    assert general_status.remaining == Decimal("0")
    assert general_status.exceeded_amount == Decimal("15.00")
    assert general_status.is_exceeded is True


# Tests that goal progress calculates remaining amount and progress percentage.
# This test exists to verify financial goal analytics business logic without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if goal progress values are calculated correctly.
def test_get_goal_progress_calculates_remaining_amount_and_progress_percent(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    goal_id = uuid4()

    goals = [
        make_model(
            id=goal_id,
            name="Vacation",
            target_amount=Decimal("2000.00"),
            current_amount=Decimal("500.00"),
            status="active",
            target_date=date(2026, 12, 31),
        ),
    ]

    def fake_get_goals(db_session: object, user_id=None):
        return goals

    monkeypatch.setattr(
        analytics_service.goals_repository,
        "get_goals",
        fake_get_goals,
    )

    # Act
    goal_progress = analytics_service.get_goal_progress(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    vacation_goal = goal_progress[0]

    assert vacation_goal.goal_id == goal_id
    assert vacation_goal.name == "Vacation"
    assert vacation_goal.target_amount == Decimal("2000.00")
    assert vacation_goal.current_amount == Decimal("500.00")
    assert vacation_goal.remaining_amount == Decimal("1500.00")
    assert vacation_goal.progress_percent == Decimal("25.00")
    assert vacation_goal.status == "active"
    assert vacation_goal.target_date == date(2026, 12, 31)


# Tests that analytics service returns empty values when repositories return no data.
# This test exists to verify empty dashboard state without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if empty analytics responses are safe and predictable.
def test_analytics_service_returns_empty_results_when_no_data_exists(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()

    def fake_get_empty_items(db_session: object, user_id=None):
        return []

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.budgets_repository,
        "get_budgets",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.goals_repository,
        "get_goals",
        fake_get_empty_items,
    )

    # Act
    monthly_summary = analytics_service.get_monthly_summary(
        db_session=db_session,
        user_id=user_id,
        year=2026,
        month=5,
    )
    category_summary = analytics_service.get_category_summary(
        db_session=db_session,
        user_id=user_id,
    )
    budget_status = analytics_service.get_budget_status(
        db_session=db_session,
        user_id=user_id,
    )
    goal_progress = analytics_service.get_goal_progress(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    assert monthly_summary.total_spent == Decimal("0")
    assert monthly_summary.expenses_count == 0
    assert category_summary == []
    assert budget_status == []
    assert goal_progress == []