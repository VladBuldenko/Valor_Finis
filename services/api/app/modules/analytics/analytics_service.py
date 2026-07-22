from collections import defaultdict
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
)
from app.modules.budgets import budget_repository as budgets_repository
from app.modules.categories import repository as categories_repository
from app.modules.expenses import expenses_repository
from app.modules.goals import goal_repository as goals_repository


UNCATEGORIZED_CATEGORY_NAME = "Uncategorized"


# Builds a category id to category name lookup map for the authenticated user.
# This function exists to avoid repeating category name search logic
# inside analytics calculations.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter categories.
# Returns:
# - Dictionary where key is category UUID and value is category name.
def build_category_name_map(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, str]:
    categories = categories_repository.get_categories(
        db_session=db_session,
        user_id=user_id,
    )

    return {
        category.id: category.name
        for category in categories
    }


# Returns a readable category name by category id.
# This function exists to keep fallback category naming consistent
# across different analytics responses.
# Parameters:
# - category_id: optional category UUID from expense or budget.
# - category_name_map: dictionary with category UUID to category name mapping.
# Returns:
# - Category name or Uncategorized when category_id is missing or unknown.
def get_category_name(
    category_id: Optional[UUID],
    category_name_map: dict[UUID, str],
) -> str:
    if category_id is None:
        return UNCATEGORIZED_CATEGORY_NAME

    return category_name_map.get(category_id, UNCATEGORIZED_CATEGORY_NAME)


# Calculates total spending and expense count for the authenticated user
# within a selected year and month.
# This function exists to provide a monthly dashboard summary.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - year: selected year used to filter expenses.
# - month: selected month used to filter expenses.
# Returns:
# - MonthlySummaryResponse with total spent and expenses count for the selected month.
def get_monthly_summary(
    db_session: Session,
    user_id: UUID,
    year: int,
    month: int,
) -> MonthlySummaryResponse:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    monthly_expenses = [
        expense
        for expense in expenses
        if expense.expense_date.year == year
        and expense.expense_date.month == month
    ]

    total_spent = sum(
        (expense.amount for expense in monthly_expenses),
        Decimal("0"),
    )

    return MonthlySummaryResponse(
        total_spent=total_spent,
        expenses_count=len(monthly_expenses),
    )


# Calculates spending grouped by category for the authenticated user.
# This function exists to show where the user's money goes.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses and categories.
# Returns:
# - List of CategorySummaryItem objects grouped by category_id.
def get_category_summary(
    db_session: Session,
    user_id: UUID,
) -> list[CategorySummaryItem]:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )
    category_name_map = build_category_name_map(
        db_session=db_session,
        user_id=user_id,
    )

    category_totals: dict[Optional[UUID], Decimal] = defaultdict(lambda: Decimal("0"))
    category_counts: dict[Optional[UUID], int] = defaultdict(int)

    for expense in expenses:
        category_totals[expense.category_id] += expense.amount
        category_counts[expense.category_id] += 1

    return [
        CategorySummaryItem(
            category_id=category_id,
            category_name=get_category_name(
                category_id=category_id,
                category_name_map=category_name_map,
            ),
            total_spent=total_spent,
            expenses_count=category_counts[category_id],
        )
        for category_id, total_spent in category_totals.items()
    ]


# Calculates budget status for each configured budget of the authenticated user.
# This function exists to show spent, remaining, and exceeded amounts.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter budgets and expenses.
# Returns:
# - List of BudgetStatusItem objects with spending status by budget.
def get_budget_status(
    db_session: Session,
    user_id: UUID,
) -> list[BudgetStatusItem]:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )
    budgets = budgets_repository.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )
    category_name_map = build_category_name_map(
        db_session=db_session,
        user_id=user_id,
    )

    budget_status: list[BudgetStatusItem] = []

    for budget in budgets:
        spent = Decimal("0")

        for expense in expenses:
            if (
                budget.category_id is not None
                and expense.category_id != budget.category_id
            ):
                continue

            if expense.expense_date < budget.start_date:
                continue

            if budget.end_date is not None and expense.expense_date > budget.end_date:
                continue

            spent += expense.amount

        remaining = max(budget.limit_amount - spent, Decimal("0"))
        exceeded_amount = max(spent - budget.limit_amount, Decimal("0"))

        budget_status.append(
            BudgetStatusItem(
                budget_id=budget.id,
                budget_name=budget.name,
                category_id=budget.category_id,
                category_name=get_category_name(
                    category_id=budget.category_id,
                    category_name_map=category_name_map,
                ),
                limit_amount=budget.limit_amount,
                spent=spent,
                remaining=remaining,
                exceeded_amount=exceeded_amount,
                is_exceeded=spent > budget.limit_amount,
            )
        )

    return budget_status


# Calculates progress for each financial goal of the authenticated user.
# This function exists to show how much money is already saved
# and how much is still needed for each goal.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter goals.
# Returns:
# - List of GoalProgressItem objects with goal progress information.
def get_goal_progress(
    db_session: Session,
    user_id: UUID,
) -> list[GoalProgressItem]:
    goals = goals_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        GoalProgressItem(
            goal_id=goal.id,
            name=goal.name,
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            remaining_amount=max(
                goal.target_amount - goal.current_amount,
                Decimal("0"),
            ),
            progress_percent=(
                goal.current_amount / goal.target_amount * Decimal("100")
            ).quantize(Decimal("0.01")),
            status=goal.status,
            target_date=goal.target_date,
        )
        for goal in goals
    ]