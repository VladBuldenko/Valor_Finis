from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
)
from app.modules.budgets import budget_repository as budgets_repository
from app.modules.expenses import expenses_repository
from app.modules.goals import goal_repository as goals_repository


# Calculates total spending and expense count.
# This function exists to provide a simple monthly dashboard summary.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - MonthlySummaryResponse with total spent and expenses count.
def get_monthly_summary(db_session: Session) -> MonthlySummaryResponse:
    expenses = expenses_repository.get_expenses(db_session)

    total_spent = sum(
        (expense.amount for expense in expenses),
        Decimal("0"),
    )

    return MonthlySummaryResponse(
        total_spent=total_spent,
        expenses_count=len(expenses),
    )


# Calculates total spending grouped by category.
# This function exists to show where the user's money goes.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of CategorySummaryItem objects grouped by category.
def get_category_summary(db_session: Session) -> list[CategorySummaryItem]:
    expenses = expenses_repository.get_expenses(db_session)
    category_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for expense in expenses:
        category_totals[expense.category] += expense.amount

    return [
        CategorySummaryItem(
            category=category,
            total_spent=total_spent,
        )
        for category, total_spent in category_totals.items()
    ]


# Calculates budget status for each configured budget limit.
# This function exists to show remaining budget and exceeded limits.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of BudgetStatusItem objects with spending status by category.
def get_budget_status(db_session: Session) -> list[BudgetStatusItem]:
    expenses = expenses_repository.get_expenses(db_session)
    budgets = budgets_repository.get_budgets(db_session)

    category_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for expense in expenses:
        category_totals[expense.category] += expense.amount

    budget_status: list[BudgetStatusItem] = []

    for budget in budgets:
        spent = category_totals.get(budget.category, Decimal("0"))
        remaining = max(budget.monthly_limit - spent, Decimal("0"))
        exceeded_amount = max(spent - budget.monthly_limit, Decimal("0"))

        budget_status.append(
            BudgetStatusItem(
                category=budget.category,
                monthly_limit=budget.monthly_limit,
                spent=spent,
                remaining=remaining,
                exceeded_amount=exceeded_amount,
                is_exceeded=spent > budget.monthly_limit,
            )
        )

    return budget_status


# Calculates progress for each financial goal.
# This function exists to show how much money is still needed for each goal.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of GoalProgressItem objects with goal progress information.
def get_goal_progress(db_session: Session) -> list[GoalProgressItem]:
    goals = goals_repository.get_goals(db_session)

    return [
        GoalProgressItem(
            name=goal.name,
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            remaining_amount=max(
                goal.target_amount - goal.current_amount,
                Decimal("0"),
            ),
        )
        for goal in goals
    ]