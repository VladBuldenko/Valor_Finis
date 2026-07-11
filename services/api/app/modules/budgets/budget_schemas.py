from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class BudgetBase(BaseModel):
    """
    Base schema containing fields shared by budget operations.

    Why:
        Prevents field duplication between request and response schemas.
    """

    category_id: Optional[UUID] = None

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        examples=["Monthly groceries"],
    )

    limit_amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        examples=["400.00"],
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        examples=["EUR"],
    )

    period: Literal["weekly", "monthly", "yearly"] = "monthly"

    start_date: date

    end_date: Optional[date] = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """
        Normalizes the currency code to uppercase.

        Why:
            Prevents values such as eur and EUR from being stored differently.

        Parameters:
            value: Currency code received from the client.

        Returns:
            Uppercase currency code.
        """

        return value.upper()

    @model_validator(mode="after")
    def validate_date_range(self) -> "BudgetBase":
        """
        Validates that the budget end date is not before its start date.

        Why:
            Prevents logically invalid budget periods.

        Returns:
            Validated budget schema.

        Raises:
            ValueError: If end_date is earlier than start_date.
        """

        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")

        return self


class BudgetCreate(BudgetBase):
    """
    Schema for creating a budget.

    Why:
        Validates incoming data before it reaches business and database layers.
        The user_id is not accepted from the client because it must come
        from authentication data.
    """

    model_config = ConfigDict(extra="forbid")


class BudgetResponse(BudgetBase):
    """
    Schema returned by the API for a budget.

    Why:
        Keeps the public API contract separate from the SQLAlchemy model.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime