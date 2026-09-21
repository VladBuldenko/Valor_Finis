from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GoalTransactionCreate(BaseModel):
    """
    Schema for creating a new goal transaction through the public API.

    What:
        Validates a client-submitted contribution or withdrawal request.

    Why:
        opening_balance must never be reachable through this schema - it is
        reserved for migration/system backfill (see goal_transaction_models.py).
        Restricting the type Literal to contribution/withdrawal makes an
        opening_balance request a validation error rather than a business
        rule that could later be bypassed or forgotten.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["contribution", "withdrawal"] = Field(
        ...,
        description="Direction of the transaction.",
        examples=["contribution"],
    )

    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Transaction amount. Always positive; direction comes from type.",
        examples=["100.00"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional free-text note.",
        examples=["Monthly savings transfer"],
    )


class GoalTransactionResponse(BaseModel):
    """
    Schema for returning goal transaction data.

    What:
        Defines the public API response shape for a goal transaction.

    Why:
        The type Literal here is deliberately wider than
        GoalTransactionCreate's: GET history must be able to represent
        migration-created opening_balance rows even though clients can never
        create one through this API.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    user_id: UUID

    type: Literal["opening_balance", "contribution", "withdrawal"] = Field(
        description="Direction of the transaction.",
        examples=["contribution"],
    )

    amount: Decimal = Field(
        max_digits=12,
        decimal_places=2,
        description="Transaction amount. Always positive; direction comes from type.",
        examples=["100.00"],
    )

    description: Optional[str] = Field(
        default=None,
        description="Optional free-text note.",
        examples=["Monthly savings transfer"],
    )

    created_at: datetime
