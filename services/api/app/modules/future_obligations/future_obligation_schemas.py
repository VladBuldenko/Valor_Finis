from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.future_obligations.future_obligation_schedule import (
    MAX_DUE_DATE,
    MIN_DUE_DATE,
    schedule_shape_error,
)

# Future obligations (VF-GOALS-PLANNING-002C1): what the user expects to owe, entered
# by hand. An obligation is a forecast input, not a transaction: creating,
# editing or archiving one never pays it, reserves money or records an Expense.

ObligationSchedule = Literal["one_time", "monthly"]
ObligationStatus = Literal["active", "archived"]

MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


# Normalizes and validates a currency code: uppercase, exactly 3 letters (each
# domain keeps its own copy, the project convention).
def normalize_and_validate_currency_code(value: str) -> str:
    normalized = value.strip().upper()

    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("currency must be exactly 3 letters.")

    return normalized


def _validate_name(value: str) -> str:
    trimmed = value.strip()

    if not trimmed:
        raise ValueError("name cannot be blank.")

    if len(trimmed) > MAX_NAME_LENGTH:
        raise ValueError(f"name must be {MAX_NAME_LENGTH} characters or fewer.")

    return trimmed


# A blank note is the same as no note, so a stored description is never "".
def _normalize_description(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    trimmed = value.strip()

    return trimmed or None


def _validate_due_date_range(value: Optional[Date]) -> Optional[Date]:
    if value is not None and not (MIN_DUE_DATE <= value <= MAX_DUE_DATE):
        raise ValueError(f"date must be between {MIN_DUE_DATE.isoformat()} and {MAX_DUE_DATE.isoformat()}.")

    return value


class FutureObligationCreate(BaseModel):
    """
    Request body to record a future obligation.

    What:
        A one-time obligation (first_due_date is its single due date, no
        final_due_date) or a monthly one (first_due_date is the first due date,
        final_due_date optionally ends it).

    Why:
        extra="forbid" rejects anything the client must not set (user_id, status,
        ids). currency defaults to the user's base currency when omitted; it is
        stored explicitly and never converted. Past due dates are accepted: a
        monthly obligation that began earlier only produces the occurrences that
        are still upcoming. All amounts have 2 decimal places.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Short label.", examples=["Car insurance"])
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH, examples=["Renewal"])
    schedule: ObligationSchedule = Field(..., examples=["monthly"])
    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
        description="Amount per due date, in currency. Always positive.",
        examples=["120.00"],
    )
    currency: Optional[str] = Field(
        default=None,
        description="3-letter currency code; omit to use the user's base currency.",
        examples=["EUR"],
    )
    first_due_date: Date = Field(
        ...,
        description="The due date (one-time) or the first due date (monthly).",
        examples=["2026-12-31"],
    )
    final_due_date: Optional[Date] = Field(
        default=None,
        description="Last due date of a monthly obligation. Not allowed for a one-time one.",
        examples=[None],
    )
    client_request_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Optional client-generated idempotency key (UUID), one per logical create, "
            "reused when that same create is retried. The same key with the same request "
            "returns the existing record (200) and creates nothing; the same key with a "
            "different request is a 409. Omit it and every request creates a new record."
        ),
        examples=[None],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_description(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_and_validate_currency_code(value)

    @field_validator("first_due_date", "final_due_date")
    @classmethod
    def validate_due_date_range(cls, value: Optional[Date]) -> Optional[Date]:
        return _validate_due_date_range(value)

    @model_validator(mode="after")
    def validate_schedule_shape(self) -> "FutureObligationCreate":
        error = schedule_shape_error(self.schedule, self.first_due_date, self.final_due_date)

        if error is not None:
            raise ValueError(error)

        return self


class FutureObligationUpdate(BaseModel):
    """
    Partial update of a future obligation (PATCH).

    What:
        Any of name, description, amount, currency, first_due_date,
        final_due_date and status. An omitted field is left unchanged;
        description and final_due_date accept an explicit null to clear them.

    Why:
        The schedule kind is not editable (a one-time and a monthly obligation
        are different things); create a new obligation instead. The schedule
        fields are validated as the RESULTING state against the stored values.
        status "archived" archives the obligation (it stays stored and
        contributes nothing); "active" restores it. Editing never pays,
        reserves or records anything.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, examples=["Car insurance"])
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    amount: Optional[Decimal] = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
        examples=["125.00"],
    )
    currency: Optional[str] = Field(default=None, examples=["EUR"])
    first_due_date: Optional[Date] = Field(default=None, examples=["2027-01-31"])
    final_due_date: Optional[Date] = Field(default=None, examples=[None])
    status: Optional[ObligationStatus] = Field(default=None, examples=["archived"])

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _validate_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_description(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_and_validate_currency_code(value)

    @field_validator("first_due_date", "final_due_date")
    @classmethod
    def validate_due_date_range(cls, value: Optional[Date]) -> Optional[Date]:
        return _validate_due_date_range(value)

    @model_validator(mode="after")
    def validate_update_payload(self) -> "FutureObligationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for a future obligation update.")

        # description and final_due_date may be null (clear); the rest may not.
        cannot_be_null = {
            "name": self.name,
            "amount": self.amount,
            "currency": self.currency,
            "first_due_date": self.first_due_date,
            "status": self.status,
        }

        for field_name, field_value in cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        return self


class FutureObligationResponse(BaseModel):
    """
    A future obligation as returned by the API.

    What:
        The stored fields plus next_due_date: the first due date on or after the
        server date, or null when the obligation is archived or has none left.

    Why:
        next_due_date is derived at read time from the server date and the
        recurrence rules; it is never stored. Amounts have 2 decimal places and
        keep their own currency; nothing is converted.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: Optional[str] = None
    schedule: ObligationSchedule
    amount: Decimal
    currency: str
    first_due_date: Date
    final_due_date: Optional[Date] = None
    status: ObligationStatus
    next_due_date: Optional[Date] = Field(
        default=None,
        description="First due date on or after the server date; null when archived or none remains.",
    )
    client_request_id: Optional[UUID] = Field(
        default=None,
        description="The create idempotency key the record was created with, or null. Read-only.",
    )
    created_at: datetime
    updated_at: datetime
