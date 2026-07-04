from datetime import date as Date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExpenseBase(BaseModel):
    """
    Base expense schema.

    What:
        Contains shared expense fields.

    Why:
        Prevents duplication between create and response schemas.
    """

    user_id: UUID
    category_id: Optional[UUID] = None
    title: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    expense_date: Date
    description: Optional[str] = None
    source: str = Field(default="manual", max_length=30)


class ExpenseCreate(ExpenseBase):
    """
    Schema for creating a new expense.

    What:
        Validates incoming request data.

    Why:
        Keeps invalid data away from service and database layers.
    """

    pass


class ExpenseResponse(ExpenseBase):
    """
    Schema for returning expense data.

    What:
        Defines API response shape.

    Why:
        Keeps database model separated from public API contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime