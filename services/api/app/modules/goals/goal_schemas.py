from datetime import date as Date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GoalBase(BaseModel):
    """
    Base goal schema.

    This schema contains common financial goal fields
    shared across goal-related schemas.

    Fields:
    - name: goal name
    - target_amount: total amount required to reach the goal
    - current_amount: amount already saved
    - deadline: date when the goal should be reached
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Financial goal name.",
        examples=["Vacation"],
    )

    target_amount: Decimal = Field(
        ...,
        gt=0,
        description="Target amount required to reach the goal.",
        examples=[2000],
    )

    current_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Amount already saved for the goal.",
        examples=[500],
    )

    deadline: Date = Field(
        ...,
        description="Date when the goal should be reached.",
        examples=["2026-12-31"],
    )


class GoalCreate(GoalBase):
    """
    Schema for creating a new financial goal.

    This schema validates incoming goal data
    before it is processed and stored.

    Inherits:
    - GoalBase
    """

    pass


class GoalResponse(GoalBase):
    """
    Schema for returning financial goal data.

    This schema defines what data the backend
    returns to the client after creating or
    retrieving financial goals.

    Additional Fields:
    - id: unique goal identifier
    - created_at: timestamp when goal was created
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime