from datetime import date as Date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BudgetBase(BaseModel):
    """
    Base budget schema.

    This schema contains common budget fields
    shared across budget-related schemas.

    Fields:
    - category: expense category key
    - monthly_limit: maximum allowed spending amount per month
    - month: month for which this budget limit is active
    """

    category: str = Field(
        ...,
        min_length=1,
        description="Expense category key.",
        examples=["food"],
    )

    monthly_limit: Decimal = Field(
        ...,
        gt=0,
        description="Monthly spending limit. Must be greater than 0.",
        examples=[400],
    )

    month: Date = Field(
        ...,
        description="Month for which the budget limit is active.",
        examples=["2026-05-01"],
    )


class BudgetCreate(BudgetBase):
    """
    Schema for creating a new budget limit.

    This schema validates incoming budget data
    before it is processed and stored.

    Inherits:
    - BudgetBase
    """

    pass


class BudgetResponse(BudgetBase):
    """
    Schema for returning budget limit data.

    This schema defines what data the backend
    returns to the client after creating or
    retrieving budget limits.

    Additional Fields:
    - id: unique budget limit identifier
    - created_at: timestamp when budget limit was created
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime