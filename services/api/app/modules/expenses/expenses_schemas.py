from datetime import date as Date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpenseBase(BaseModel):
    """
    Base expense schema.

    What:
        Contains shared expense fields.

    Why:
        Prevents duplication between create and response schemas.
    """

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
        Validates incoming request data from the client.

    Why:
        Keeps invalid data away from service and database layers.
        The user_id is not accepted from the client because it must come
        from authentication data.
    """

    model_config = ConfigDict(extra="forbid")


class ExpenseUpdate(BaseModel):
    """
    Schema for updating an existing expense.

    What:
        Validates partial expense update data.

    Why:
        Allows users to update only selected fields while preventing
        empty update requests and invalid null values for required fields.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: Optional[UUID] = Field(
        default=None,
        description="Updated category identifier. Null means uncategorized expense.",
    )
    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Updated expense title.",
        examples=["Updated groceries"],
    )
    amount: Optional[Decimal] = Field(
        default=None,
        gt=0,
        description="Updated expense amount.",
        examples=["35.50"],
    )
    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Updated currency code.",
        examples=["EUR"],
    )
    expense_date: Optional[Date] = Field(
        default=None,
        description="Updated expense date.",
        examples=["2026-05-08"],
    )
    description: Optional[str] = Field(
        default=None,
        description="Updated optional expense description.",
        examples=["Updated description"],
    )
    source: Optional[str] = Field(
        default=None,
        max_length=30,
        description="Updated expense source.",
        examples=["manual"],
    )

    @model_validator(mode="after")
    def validate_update_payload(self) -> "ExpenseUpdate":
        """
        Validates that the update request contains at least one field.

        What:
            Checks that the client sent at least one editable field.

        Why:
            Prevents empty PATCH requests that do not change anything.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for expense update.")

        fields_that_cannot_be_null = {
            "title": self.title,
            "amount": self.amount,
            "currency": self.currency,
            "expense_date": self.expense_date,
            "source": self.source,
        }

        for field_name, field_value in fields_that_cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        return self


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
    user_id: UUID
    created_at: datetime
    updated_at: datetime