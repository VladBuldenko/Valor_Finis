from datetime import date as Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ExpenseBase(BaseModel):
    """
    Base expense schema.

    This schema contains common expense fields
    shared across multiple expense-related schemas.

    Fields:
    - amount: expense amount
    - category: expense category
    - description: optional expense description
    - date: date when expense happened
    """

    amount: Decimal = Field(
        ...,
        gt=0,
        description="Expense amount. Must be greater than 0.",
        examples=[24.99],
    )

    category: str = Field(
        ...,
        min_length=1,
        description="Expense category.",
        examples=["food"],
    )

    description: Optional[str] = Field(
        default=None,
        description="Optional expense description.",
        examples=["Lidl groceries"],
    )

    date: Date = Field(
        ...,
        description="Date when the expense happened.",
        examples=["2026-05-07"],
    )


class ExpenseCreate(ExpenseBase):
    """
    Schema for creating a new expense.

    This schema validates incoming expense data
    before it is processed and stored.

    Inherits:
    - ExpenseBase
    """

    pass


class ExpenseResponse(ExpenseBase):
    """
    Schema for returning expense data.

    This schema defines what data the backend
    returns to the client after creating or
    retrieving expenses.

    Additional Fields:
    - id: unique expense identifier
    - created_at: timestamp when expense was created
    """

    model_config = ConfigDict(from_attributes=True)

    id: int

    created_at: datetime