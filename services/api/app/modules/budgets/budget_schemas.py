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


# Validates a budget name sent by a client: trimmed and not blank.
# This function exists so the request schemas reject a name made only of
# whitespace and never store leading/trailing spaces, as Accounts do. It is
# applied to requests only, never to BudgetResponse, so a row that already
# exists can always be read back.
# Parameters:
# - value: raw name from the client.
# Returns:
# - The trimmed name.
# Raises:
# - ValueError: when the trimmed name is empty.
def _normalize_budget_name(value: str) -> str:
    trimmed = value.strip()

    if not trimmed:
        raise ValueError("name cannot be blank.")

    return trimmed


# Validates a currency code sent by a client: exactly three letters A-Z.
# This function exists to apply the same shape rule Expenses, Income and
# Accounts already enforce, so a code such as "E1R" or "12 " can never
# become a budget that no expense can match. Request schemas only.
# Parameters:
# - value: currency code, already upper-cased and stripped by the base schema.
# Returns:
# - The validated code.
# Raises:
# - ValueError: when it is not exactly three ASCII letters.
def _validate_budget_currency(value: str) -> str:
    if len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValueError("currency must be exactly 3 alphabetic characters.")

    return value


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

        return value.strip().upper()

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

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_budget_name(value)

    @field_validator("currency")
    @classmethod
    def validate_currency_shape(cls, value: str) -> str:
        return _validate_budget_currency(value)


class BudgetUpdate(BaseModel):
    """
    Schema for updating an existing budget.

    What:
        Validates partial budget update data.

    Why:
        Allows users to update only selected budget fields while preventing
        empty update requests and invalid null values for required fields.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: Optional[UUID] = Field(
        default=None,
        description="Updated category identifier. Null means general budget.",
    )

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Updated budget name.",
        examples=["Updated groceries budget"],
    )

    limit_amount: Optional[Decimal] = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Updated budget limit amount.",
        examples=["500.00"],
    )

    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Updated currency code.",
        examples=["EUR"],
    )

    period: Optional[Literal["weekly", "monthly", "yearly"]] = Field(
        default=None,
        description="Updated budget period.",
        examples=["monthly"],
    )

    start_date: Optional[date] = Field(
        default=None,
        description="Updated budget start date.",
        examples=["2026-05-01"],
    )

    end_date: Optional[date] = Field(
        default=None,
        description="Updated budget end date. Null means no end date.",
        examples=["2026-05-31"],
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalizes the currency code to uppercase.

        Why:
            Prevents values such as eur and EUR from being stored differently.

        Parameters:
            value: Optional currency code received from the client.

        Returns:
            Uppercase currency code or None.
        """

        if value is None:
            return value

        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        return _normalize_budget_name(value)

    @field_validator("currency")
    @classmethod
    def validate_currency_shape(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        return _validate_budget_currency(value)

    @model_validator(mode="after")
    def validate_update_payload(self) -> "BudgetUpdate":
        """
        Validates that the update request contains at least one field.

        What:
            Checks that the client sent at least one editable field.

        Why:
            Prevents empty PATCH requests that do not change anything.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for budget update.")

        fields_that_cannot_be_null = {
            "name": self.name,
            "limit_amount": self.limit_amount,
            "currency": self.currency,
            "period": self.period,
            "start_date": self.start_date,
        }

        for field_name, field_value in fields_that_cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be greater than or equal to start_date")

        return self


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