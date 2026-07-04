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


class GoalBase(BaseModel):
    """
    Base schema containing fields shared by goal operations.

    What:
        Defines common financial goal fields.

    Why:
        Prevents duplication between create and response schemas.
    """

    user_id: UUID = Field(
        ...,
        description="User identifier that owns this financial goal.",
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Financial goal name.",
        examples=["Vacation"],
    )

    target_amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Target amount required to reach the goal.",
        examples=["2000.00"],
    )

    current_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Amount already saved for the goal.",
        examples=["500.00"],
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        description="Currency code.",
        examples=["EUR"],
    )

    target_date: Optional[date] = Field(
        default=None,
        description="Optional date when the user wants to reach the goal.",
        examples=["2026-12-31"],
    )

    status: Literal["active", "completed", "archived"] = Field(
        default="active",
        description="Current goal status.",
        examples=["active"],
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """
        Normalizes the currency code to uppercase.

        What:
            Converts currency values such as eur to EUR.

        Why:
            Prevents storing the same currency in different formats.

        Parameters:
            value: Currency code received from the client.

        Returns:
            Uppercase currency code.
        """

        return value.upper()

    @model_validator(mode="after")
    def validate_goal_amounts(self) -> "GoalBase":
        """
        Validates financial goal amount consistency.

        What:
            Checks that current_amount does not exceed target_amount.

        Why:
            Prevents logically invalid financial goals.

        Parameters:
            None.

        Returns:
            Validated GoalBase object.

        Raises:
            ValueError: If current_amount is greater than target_amount.
        """

        if self.current_amount > self.target_amount:
            raise ValueError("current_amount must be less than or equal to target_amount")

        return self


class GoalCreate(GoalBase):
    """
    Schema for creating a new financial goal.

    What:
        Validates incoming goal data before it reaches service and repository layers.

    Why:
        Keeps invalid client input away from business logic and database logic.
    """

    pass


class GoalResponse(GoalBase):
    """
    Schema for returning financial goal data.

    What:
        Defines the public API response shape for goals.

    Why:
        Keeps the database model separated from the API contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime