from datetime import date as Date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Normalizes and validates a currency code: uppercase, exactly 3
# alphabetic characters.
# This function exists so Expense enforces a real (if minimal) currency
# code shape rather than the plain length check the schema previously
# relied on - a garbage value like "123" or "X-Y" no longer passes.
# Provider support (which currencies FX resolution can actually convert)
# is a separate, later concern - see app/modules/fx - not checked here.
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

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return normalize_and_validate_currency_code(value)


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

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        return normalize_and_validate_currency_code(value)

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
        Defines API response shape. amount/currency keep their original
        meaning: the transaction as it actually happened, never revalued.
        base_amount/base_currency/fx_rate/fx_rate_date/fx_source (VF-014B5C)
        are backend-derived read-only fields exposing that same
        transaction converted to the user's base currency, using the
        historical rate in effect on expense_date. All five are Optional
        only to truthfully represent a legacy foreign expense created
        before VF-014B5C, whose snapshot has not been resolved yet - for
        every expense created after VF-014B5C, all five are always
        populated together.

    Why:
        Keeps database model separated from public API contract. These
        fields are never accepted on ExpenseCreate/ExpenseUpdate - the
        client can only ever submit original transaction truth.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID

    base_amount: Optional[Decimal] = Field(
        default=None,
        description=(
            "amount converted to the user's base currency, using the "
            "historical rate in effect on expense_date. Null only for an "
            "unresolved legacy foreign expense."
        ),
        examples=["84.73"],
    )
    base_currency: Optional[str] = Field(
        default=None,
        description="The base currency base_amount is denominated in.",
        examples=["EUR"],
    )
    fx_rate: Optional[Decimal] = Field(
        default=None,
        description="Units of base_currency per 1 unit of currency.",
        examples=["0.84730000"],
    )
    fx_rate_date: Optional[Date] = Field(
        default=None,
        description=(
            "The actual published rate date used - may differ from "
            "expense_date (weekends/holidays), never later than it."
        ),
        examples=["2026-09-15"],
    )
    fx_source: Optional[str] = Field(
        default=None,
        description='"identity", "ecb", or "nbu".',
        examples=["ecb"],
    )
    created_at: datetime
    updated_at: datetime