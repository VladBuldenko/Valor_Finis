from decimal import Decimal

from pydantic import BaseModel, Field


class MonthlySummaryResponse(BaseModel):
    """
    Schema for monthly spending summary.

    Fields:
    - total_spent: total amount spent in the selected month
    - expenses_count: number of expenses in the selected month
    """

    total_spent: Decimal = Field(
        ...,
        description="Total amount spent in the selected month.",
        examples=[1200],
    )

    expenses_count: int = Field(
        ...,
        description="Number of expenses in the selected month.",
        examples=[25],
    )


class CategorySummaryItem(BaseModel):
    """
    Schema for spending summary by category.

    Fields:
    - category: expense category key
    - total_spent: total amount spent in this category
    """

    category: str = Field(
        ...,
        description="Expense category key.",
        examples=["food"],
    )

    total_spent: Decimal = Field(
        ...,
        description="Total amount spent in this category.",
        examples=[400],
    )


class BudgetStatusItem(BaseModel):
    """
    Schema for budget status by category.

    Fields:
    - category: expense category key
    - monthly_limit: configured monthly budget limit
    - spent: amount already spent in this category
    - remaining: amount remaining before reaching the limit
    - exceeded_amount: amount above the limit
    - is_exceeded: whether the budget limit is exceeded
    """

    category: str
    monthly_limit: Decimal
    spent: Decimal
    remaining: Decimal
    exceeded_amount: Decimal
    is_exceeded: bool


class GoalProgressItem(BaseModel):
    """
    Schema for financial goal progress.

    Fields:
    - name: goal name
    - target_amount: required amount to reach the goal
    - current_amount: amount already saved
    - remaining_amount: amount still needed
    """

    name: str
    target_amount: Decimal
    current_amount: Decimal
    remaining_amount: Decimal