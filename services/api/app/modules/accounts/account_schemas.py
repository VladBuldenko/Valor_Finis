from datetime import date as Date, datetime
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


# Normalizes and validates a currency code: uppercase, exactly 3
# alphabetic characters.
# This function exists so Account enforces the same real currency-code
# shape Expense already enforces, rather than only the length check a
# bare Field(min_length=3, max_length=3) would give. Provider support
# (which currencies FX resolution can actually convert) is unrelated -
# Account never resolves FX in this slice.
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


class AccountBase(BaseModel):
    """
    Base schema containing fields shared by account operations.

    What:
        Defines common account fields.

    Why:
        Prevents duplication between create and response schemas.
        current_balance is deliberately NOT part of this shared base: it
        is not client-writable at all. Direct funding happens only through
        an AccountTransaction (see account_transaction_schemas.py) or the
        opening_balance accepted on AccountCreate; AccountResponse adds
        current_balance back itself as a read-only, ledger-derived field -
        the Account row has no balance storage of its own.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Account name.",
        examples=["Main Checking"],
    )

    type: Literal["checking", "savings", "cash"] = Field(
        ...,
        description="Kind of real-world account this represents.",
        examples=["checking"],
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        description="Currency code.",
        examples=["EUR"],
    )

    status: Literal["active", "archived"] = Field(
        default="active",
        description="Current account status.",
        examples=["active"],
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """
        Trims surrounding whitespace from the account name.

        What:
            Strips leading/trailing whitespace before length validation.

        Why:
            Prevents storing accidental leading/trailing spaces and
            prevents a whitespace-only name from passing min_length=1.

        Parameters:
            value: Raw account name from the client.

        Returns:
            Trimmed account name.
        """

        trimmed = value.strip()

        if not trimmed:
            raise ValueError("name cannot be blank.")

        return trimmed

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return normalize_and_validate_currency_code(value)


class AccountCreate(AccountBase):
    """
    Schema for creating a new account.

    What:
        Validates incoming account data before it reaches service and
        repository layers.

    Why:
        Keeps invalid client input away from business logic and database
        logic. user_id is not accepted from the client because it must
        come from authentication data. current_balance is not accepted at
        all (extra="forbid" rejects it) - a new account starts at 0 unless
        opening_balance is given, in which case exactly one immutable
        opening_balance AccountTransaction is created atomically with the
        Account row (see account_service.create_account). This is a
        deliberate difference from GoalCreate (which never accepts a
        starting balance): a Goal is always aspirational and starts at
        zero by definition, while an Account being onboarded typically
        represents money that already exists right now.
    """

    model_config = ConfigDict(extra="forbid")

    opening_balance: Optional[Decimal] = Field(
        default=None,
        max_digits=12,
        decimal_places=2,
        description=(
            "Optional signed starting balance for a real pre-existing "
            "account. Positive creates a credit opening_balance "
            "transaction, negative creates a debit one, null/zero creates "
            "no transaction at all. Never persisted as a field - always "
            "converted into a ledger transaction."
        ),
        examples=["1000.00"],
    )

    opening_balance_date: Optional[Date] = Field(
        default=None,
        description=(
            "Date the opening balance is as of. Defaults to today when "
            "opening_balance is non-zero and this is omitted. Ignored "
            "when opening_balance is null or zero."
        ),
        examples=["2026-09-23"],
    )


class AccountUpdate(BaseModel):
    """
    Schema for updating an existing account.

    What:
        Validates partial account update data.

    Why:
        Allows users to update only selected account fields while
        preventing empty update requests and invalid null values for
        required fields. currency changes are validated for immutability
        in the service layer, not here (that check depends on whether
        transaction history exists, which requires a database read).
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Updated account name.",
        examples=["Joint Checking"],
    )

    type: Optional[Literal["checking", "savings", "cash"]] = Field(
        default=None,
        description="Updated account type.",
        examples=["savings"],
    )

    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Updated currency code.",
        examples=["EUR"],
    )

    status: Optional[Literal["active", "archived"]] = Field(
        default=None,
        description="Updated account status.",
        examples=["archived"],
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        trimmed = value.strip()

        if not trimmed:
            raise ValueError("name cannot be blank.")

        return trimmed

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        return normalize_and_validate_currency_code(value)

    @model_validator(mode="after")
    def validate_update_payload(self) -> "AccountUpdate":
        """
        Validates partial account update data.

        What:
            Checks that the request contains at least one field and that
            required account fields are not explicitly set to null.

        Why:
            Prevents empty PATCH requests and invalid account state.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for account update.")

        fields_that_cannot_be_null = {
            "name": self.name,
            "type": self.type,
            "currency": self.currency,
            "status": self.status,
        }

        for field_name, field_value in fields_that_cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        return self


class AccountResponse(AccountBase):
    """
    Schema for returning account data.

    What:
        Defines the public API response shape for accounts.

    Why:
        Keeps the database model separated from the API contract.
        current_balance is read-only and ledger-derived: it is computed
        from the account_transactions ledger at read time
        (SUM of credit amounts minus debit amounts) every time an Account
        is returned, never accepted as client input, and never persisted
        on the Account row itself. Unlike Goal.current_amount,
        current_balance has no ge=0 constraint - an Account is a
        descriptive financial record, not a payment-authorization system,
        so a negative balance (e.g. an opening balance followed by a
        larger debit adjustment) is a valid, representable state.

        current_balance deliberately has NO max_digits constraint, unlike
        AccountTransaction.amount (NUMERIC(12,2) on every persisted row).
        A single transaction's amount is correctly bounded to 12 digits,
        but current_balance is the SUM of arbitrarily many valid rows -
        e.g. two individually valid 9,000,000,000.00 credits sum to
        18,000,000,000.00, which is a perfectly valid ledger balance that
        must not fail response validation merely because it exceeds one
        row's own storage range. decimal_places=2 is kept since every
        summand shares that scale, so the sum always does too.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID

    current_balance: Decimal = Field(
        decimal_places=2,
        description=(
            "Current balance, computed from the account_transactions "
            "ledger. Read-only. May be negative, zero, or positive, and "
            "may exceed a single transaction's own NUMERIC(12,2) range "
            "since it is a sum of arbitrarily many rows."
        ),
        examples=["874.50"],
    )

    created_at: datetime
    updated_at: datetime
