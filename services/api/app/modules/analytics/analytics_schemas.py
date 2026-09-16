from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MonthlySummaryResponse(BaseModel):
    """
    Schema for a high-level spending summary.

    What:
        Represents total spending and number of expenses.

    Why:
        Provides a simple dashboard overview for web and mobile clients.
    """

    total_spent: Decimal = Field(
        ...,
        description="Total amount spent.",
        examples=["250.75"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description="Number of expense records.",
        examples=[12],
    )


class CategorySummaryItem(BaseModel):
    """
    Schema for spending summary grouped by category.

    What:
        Represents total spending and expense count for one category.

    Why:
        Helps the user understand where money is spent.
    """

    category_id: Optional[UUID] = Field(
        default=None,
        description="Category identifier. Null means uncategorized expenses.",
    )

    category_name: str = Field(
        ...,
        description="Human-readable category name.",
        examples=["Food"],
    )

    total_spent: Decimal = Field(
        ...,
        description="Total amount spent in this category.",
        examples=["120.50"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description="Number of expenses in this category.",
        examples=[5],
    )


class BudgetStatusItem(BaseModel):
    """
    Schema for budget usage status.

    What:
        Represents how much was spent against a configured budget.

    Why:
        Helps the user see remaining budget and exceeded amounts.
    """

    budget_id: UUID = Field(
        ...,
        description="Budget identifier.",
    )

    budget_name: str = Field(
        ...,
        description="Human-readable budget name.",
        examples=["Monthly groceries"],
    )

    category_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Category identifier scoping this budget, resolved from the "
            "BudgetVersion applicable to the current period."
        ),
    )

    category_name: str = Field(
        ...,
        description="Human-readable category name or Uncategorized.",
        examples=["Food"],
    )

    period: Literal["weekly", "monthly", "yearly"] = Field(
        ...,
        description="Recurrence unit this budget resets on.",
        examples=["monthly"],
    )

    period_start: date = Field(
        ...,
        description="Inclusive start of the calendar period this status covers.",
        examples=["2026-09-01"],
    )

    period_end: date = Field(
        ...,
        description="Inclusive end of the calendar period this status covers.",
        examples=["2026-09-30"],
    )

    effective_start: date = Field(
        ...,
        description=(
            "period_start clamped to the budget's activation date - where "
            "spending is actually counted from."
        ),
        examples=["2026-09-01"],
    )

    effective_end: date = Field(
        ...,
        description=(
            "period_end clamped to the budget's deactivation date, if any."
        ),
        examples=["2026-09-30"],
    )

    period_state: Literal["not_started", "active", "ended"] = Field(
        ...,
        description="Whether the budget's activation window has started/ended.",
        examples=["active"],
    )

    is_partial_period: bool = Field(
        ...,
        description=(
            "True when the budget's activation or deactivation date clips "
            "this calendar period."
        ),
        examples=[False],
    )

    limit_amount: Decimal = Field(
        ...,
        description=(
            "Limit in effect for this period, resolved from BudgetVersion "
            "history rather than the budget's current value."
        ),
        examples=["400.00"],
    )

    spent: Decimal = Field(
        ...,
        description="Amount already spent within the budget period.",
        examples=["250.00"],
    )

    remaining: Decimal = Field(
        ...,
        description="Amount still available before exceeding the budget.",
        examples=["150.00"],
    )

    exceeded_amount: Decimal = Field(
        ...,
        description="Amount by which the budget was exceeded.",
        examples=["0.00"],
    )

    utilization_percent: Decimal = Field(
        ...,
        description=(
            "spent / limit_amount * 100. Not clamped - an exceeded budget "
            "can read above 100."
        ),
        examples=["62.50"],
    )

    is_exceeded: bool = Field(
        ...,
        description="Shows whether spending is greater than the budget limit.",
        examples=[False],
    )


class GoalProgressItem(BaseModel):
    """
    Schema for financial goal progress.

    What:
        Represents saved amount, remaining amount, and progress percentage.

    Why:
        Helps the user understand how close they are to reaching a goal.
    """

    goal_id: UUID = Field(
        ...,
        description="Financial goal identifier.",
    )

    name: str = Field(
        ...,
        description="Financial goal name.",
        examples=["Vacation"],
    )

    target_amount: Decimal = Field(
        ...,
        description="Target amount required to complete the goal.",
        examples=["2000.00"],
    )

    current_amount: Decimal = Field(
        ...,
        description="Amount already saved toward the goal.",
        examples=["500.00"],
    )

    remaining_amount: Decimal = Field(
        ...,
        description="Amount still needed to reach the goal.",
        examples=["1500.00"],
    )

    progress_percent: Decimal = Field(
        ...,
        description="Goal completion percentage from 0 to 100.",
        examples=["25.00"],
    )

    status: str = Field(
        ...,
        description="Current goal status.",
        examples=["active"],
    )

    target_date: Optional[date] = Field(
        default=None,
        description="Optional target date for reaching the goal.",
        examples=["2026-12-31"],
    )