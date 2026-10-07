import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# effective_date is a calendar date only: an ISO "YYYY-MM-DD" string (or a
# date object in Python). Datetime strings, datetime objects and numeric
# timestamps are rejected so no timezone ever influences which day is
# recorded (VF-020B3).
EFFECTIVE_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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

        currency is deliberately absent: the service always copies it from
        the owning goal, and extra="forbid" rejects a client-sent currency.
        effective_date and client_request_id (VF-020B3) are optional: an
        omitted (or null) effective_date means the server date; the future
        date rule depends on the server date, so the service enforces it.
        client_request_id stays optional during the rollout so older clients
        keep working; current clients always send one.
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

    effective_date: Optional[date] = Field(
        default=None,
        description=(
            "Business date of the transaction (YYYY-MM-DD). Defaults to the "
            "server date when omitted; must not be in the future."
        ),
        examples=["2026-10-05"],
    )

    client_request_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Client-generated idempotency key. Reusing it with the same "
            "payload returns the original transaction (200); with a "
            "different payload it is rejected (409)."
        ),
        examples=["5f0c6a8e-3d2b-4c1a-9e7f-2b8d4a6c1e90"],
    )

    # Restricts effective_date to a pure calendar date before Pydantic's
    # lenient date parsing runs (which would also accept zero-time datetimes
    # and Unix timestamps).
    # Parameters:
    # - value: raw effective_date input.
    # Returns:
    # - The unchanged value when it is None, a date, or a YYYY-MM-DD string.
    # Raises:
    # - ValueError: for any other form.
    @field_validator("effective_date", mode="before")
    @classmethod
    def require_calendar_date(cls, value: Any) -> Any:
        if value is None:
            return value

        if isinstance(value, date) and not isinstance(value, datetime):
            return value

        if isinstance(value, str) and EFFECTIVE_DATE_PATTERN.fullmatch(value):
            return value

        raise ValueError("effective_date must be a calendar date in YYYY-MM-DD format")


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

        currency, effective_date and client_request_id (VF-020B3) are
        nullable in the response: effective_date is NULL for older history
        (never derived from created_at), and client_request_id is NULL for
        every row created without a key. Once the VF-020B4 migration is
        applied, currency is never NULL in the database, but the response
        field deliberately stays optional: this code must keep serializing
        rows correctly while it runs against a database where that
        migration has not been applied yet (the application is deployed
        before the migration is applied to production). It can be
        tightened to a required field in a later change, after the
        migration is applied everywhere.
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

    currency: Optional[str] = Field(
        default=None,
        description="Currency of the amount (the goal's currency); never null once the VF-020B4 migration is applied.",
        examples=["EUR"],
    )

    effective_date: Optional[date] = Field(
        default=None,
        description="Business date of the transaction; null only for older history.",
        examples=["2026-10-05"],
    )

    client_request_id: Optional[UUID] = Field(
        default=None,
        description="Idempotency key sent with the create request, if any.",
    )
