from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INCOME_SOURCES = ("salary", "freelance", "refund", "gift", "other")


# Normalizes and validates a currency code: uppercase, exactly 3
# alphabetic characters.
# This function exists so Income enforces the same real currency-code
# shape Expense already enforces (expenses_schemas.normalize_and_
# validate_currency_code). Not imported from expenses_schemas directly -
# each domain module keeps its own copy, matching the existing project
# convention (Goal, Budget, Receipt each define their own currency
# normalizer rather than sharing one across module boundaries).
# Parameters:
# - value: raw currency code from the client.
# Returns:
# - Uppercase, validated 3-letter currency code.
# Raises:
# - ValueError: when the code is not exactly 3 alphabetic characters.
def normalize_and_validate_currency_code(value: str) -> str:
    normalized = value.strip().upper()

    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be exactly 3 alphabetic characters.")

    return normalized


class IncomeBase(BaseModel):
    """
    Base schema containing fields shared by income operations.

    What:
        Defines common income fields.

    Why:
        Prevents duplication between create and response schemas.

        Deliberately has NO account_id field (VF-017C). An account_id
        field would claim "this income belongs to Account X" while
        having zero effect on that Account's balance in this slice -
        linking Income to an Account only becomes meaningful once it
        atomically creates/synchronizes an AccountTransaction, which is
        VF-017D's job, not this one. Adding the field now, unused, would
        be a semantically false contract.
    """

    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Amount received, in currency. Always positive.",
        examples=["2500.00"],
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        description="Currency code.",
        examples=["EUR"],
    )

    received_at: Date = Field(
        ...,
        description="Date the money was actually received.",
        examples=["2026-09-23"],
    )

    source: Literal["salary", "freelance", "refund", "gift", "other"] = Field(
        ...,
        description="What kind of income this is.",
        examples=["salary"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional free-text note.",
        examples=["September salary"],
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return normalize_and_validate_currency_code(value)


class IncomeCreate(IncomeBase):
    """
    Schema for creating a new income record.

    What:
        Validates incoming income data before it reaches service and
        repository layers.

    Why:
        Keeps invalid client input away from business logic and database
        logic. user_id is not accepted from the client because it must
        come from authentication data. The five FX snapshot fields are
        not accepted either (extra="forbid" rejects them) - they are
        always backend-resolved (see income_service.create_income).
    """

    model_config = ConfigDict(extra="forbid")


class IncomeUpdate(BaseModel):
    """
    Schema for updating an existing income record.

    What:
        Validates partial income update data.

    Why:
        Allows users to update only selected income fields while
        preventing empty update requests and invalid null values for
        required fields.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Optional[Decimal] = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Updated amount received.",
        examples=["2600.00"],
    )

    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Updated currency code.",
        examples=["EUR"],
    )

    received_at: Optional[Date] = Field(
        default=None,
        description="Updated date the money was actually received.",
        examples=["2026-09-24"],
    )

    source: Optional[Literal["salary", "freelance", "refund", "gift", "other"]] = Field(
        default=None,
        description="Updated income source.",
        examples=["freelance"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated optional free-text note.",
        examples=["Updated note"],
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        return normalize_and_validate_currency_code(value)

    @model_validator(mode="after")
    def validate_update_payload(self) -> "IncomeUpdate":
        """
        Validates partial income update data.

        What:
            Checks that the request contains at least one field and that
            required income fields are not explicitly set to null.

        Why:
            Prevents empty PATCH requests and invalid income state.
            description is deliberately excluded from the
            cannot-be-null set: null is how a client clears an existing
            note, matching Expense's own description-nullability
            convention.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for income update.")

        fields_that_cannot_be_null = {
            "amount": self.amount,
            "currency": self.currency,
            "received_at": self.received_at,
            "source": self.source,
        }

        for field_name, field_value in fields_that_cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        return self


class IncomeResponse(IncomeBase):
    """
    Schema for returning income data.

    What:
        Defines the public API response shape for income. amount/currency
        keep their original meaning: the amount as actually received,
        never revalued. base_amount/base_currency/fx_rate/fx_rate_date/
        fx_source are backend-derived read-only fields exposing that same
        amount converted to the user's base currency, using the
        historical rate in effect on received_at - identical semantics to
        ExpenseResponse's FX fields, reusing the same FX architecture.

    Why:
        Keeps the database model separated from the API contract. These
        five fields are never accepted on IncomeCreate/IncomeUpdate - the
        client can only ever submit original transaction truth. Unlike
        Expense (which has legacy pre-FX rows), every Income row is
        created after this snapshot logic exists, so all five are always
        populated together for every row - still modeled as Optional to
        keep the response schema an honest mirror of the nullable-together
        database columns, not because an unresolved Income can exist.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID

    base_amount: Optional[Decimal] = Field(
        default=None,
        description=(
            "amount converted to the user's base currency, using the "
            "historical rate in effect on received_at. Read-only."
        ),
        examples=["2500.00"],
    )
    base_currency: Optional[str] = Field(
        default=None,
        description="The base currency base_amount is denominated in.",
        examples=["EUR"],
    )
    fx_rate: Optional[Decimal] = Field(
        default=None,
        description="Units of base_currency per 1 unit of currency.",
        examples=["1.00000000"],
    )
    fx_rate_date: Optional[Date] = Field(
        default=None,
        description=(
            "The actual published rate date used - may differ from "
            "received_at (weekends/holidays), never later than it."
        ),
        examples=["2026-09-23"],
    )
    fx_source: Optional[str] = Field(
        default=None,
        description='"identity", "ecb", or "nbu".',
        examples=["identity"],
    )
    created_at: datetime
    updated_at: datetime
