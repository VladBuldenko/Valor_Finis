import re
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

# Exactly three ASCII uppercase letters. Python's [A-Z] never matches
# non-ASCII letters, unlike str.isalpha().
GOAL_CURRENCY_CODE_PATTERN = re.compile(r"[A-Z]{3}")


# Normalizes and validates a Goal currency code (VF-020B1).
# This function exists because a Goal currency must be a plain three-letter
# ASCII code: "eur" is accepted as "EUR", while values such as "12$",
# "E1R", "ÉUR" or "ıNR" are rejected with a validation error (422). It is
# deliberately stricter than the Account/Income/Expense validators, whose
# str.isalpha() check also accepts non-ASCII letters; those are unchanged.
# The input is checked for non-ASCII characters BEFORE uppercasing, because
# str.upper() maps a few non-ASCII letters to ASCII ("ı" -> "I",
# "ſ" -> "S") and would otherwise let "ıNR" pass as "INR".
# Parameters:
# - value: currency code received from the client, already length-checked
#   by the field's min_length/max_length constraints.
# Returns:
# - The normalized uppercase currency code.
# Raises:
# - ValueError: when the trimmed input contains a non-ASCII character or
#   the normalized value is not exactly three ASCII letters.
def normalize_and_validate_goal_currency_code(value: str) -> str:
    stripped = value.strip()

    if not stripped.isascii():
        raise ValueError("currency must be exactly 3 ASCII letters (A-Z).")

    normalized = stripped.upper()

    if GOAL_CURRENCY_CODE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("currency must be exactly 3 ASCII letters (A-Z).")

    return normalized


class GoalBase(BaseModel):
    """
    Base schema containing fields shared by goal operations.

    What:
        Defines common financial goal fields.

    Why:
        Prevents duplication between create and response schemas.
        current_amount is deliberately NOT part of this shared base: it is
        not client-writable at all (VF-016). Funding happens only through a
        GoalTransaction (see goal_transaction_schemas.py); GoalResponse adds
        current_amount back itself as a read-only, ledger-derived field -
        the Goal row has no balance storage of its own (VF-016G).
    """

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
            GoalResponse inherits this lenient normalization on purpose:
            it does not enforce the strict ASCII rule that GoalCreate and
            GoalUpdate apply to client input (VF-020B1), so a goal stored
            earlier with a three-character value that fails the new rule
            (for example "12$") stays readable. The field's length
            constraints still apply to responses; the quality of stored
            historical currency data is verified separately by the
            VF-020B2 production preflight.

        Parameters:
            value: Currency code received from the client.

        Returns:
            Uppercase currency code.
        """

        return value.strip().upper()


class GoalCreate(GoalBase):
    """
    Schema for creating a new financial goal.

    What:
        Validates incoming goal data before it reaches service and repository layers.

    Why:
        Keeps invalid client input away from business logic and database logic.
        The user_id is not accepted from the client because it must come
        from authentication data. current_amount is not accepted either
        (extra="forbid" rejects it): every new Goal starts at 0 and can only
        be funded afterward through a contribution GoalTransaction.
    """

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """
        Normalizes and validates the currency code of a new goal.

        What:
            Converts currency values such as eur to EUR and rejects
            anything that is not exactly three ASCII letters.

        Why:
            Prevents storing the same currency in different formats and
            prevents invalid codes such as 12$ or ÉUR from being stored
            (VF-020B1). Overrides GoalBase's lenient normalizer for input.

        Parameters:
            value: Currency code received from the client.

        Returns:
            Uppercase three-letter ASCII currency code.
        """

        return normalize_and_validate_goal_currency_code(value)


class GoalUpdate(BaseModel):
    """
    Schema for updating an existing financial goal.

    What:
        Validates partial goal update data.

    Why:
        Allows users to update only selected goal fields while preventing
        empty update requests and invalid null values for required fields.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="Updated financial goal name.",
        examples=["Updated vacation"],
    )

    target_amount: Optional[Decimal] = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Updated target amount required to reach the goal.",
        examples=["2500.00"],
    )

    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Updated currency code.",
        examples=["EUR"],
    )

    target_date: Optional[date] = Field(
        default=None,
        description="Updated target date. Null means no target date.",
        examples=["2026-12-31"],
    )

    status: Optional[Literal["active", "completed", "archived"]] = Field(
        default=None,
        description="Updated goal status.",
        examples=["completed"],
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalizes and validates the currency code.

        What:
            Converts currency values such as eur to EUR and rejects
            anything that is not exactly three ASCII letters.

        Why:
            Prevents storing the same currency in different formats and
            prevents invalid codes such as 12$ or ÉUR from being stored.

        Parameters:
            value: Optional currency code received from the client.

        Returns:
            Uppercase three-letter ASCII currency code or None.
        """

        if value is None:
            return value

        return normalize_and_validate_goal_currency_code(value)

    @model_validator(mode="after")
    def validate_update_payload(self) -> "GoalUpdate":
        """
        Validates partial goal update data.

        What:
            Checks that the request contains at least one field and that
            required goal fields are not explicitly set to null.

        Why:
            Prevents empty PATCH requests and invalid goal state.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for goal update.")

        fields_that_cannot_be_null = {
            "name": self.name,
            "target_amount": self.target_amount,
            "currency": self.currency,
            "status": self.status,
        }

        for field_name, field_value in fields_that_cannot_be_null.items():
            if field_name in self.model_fields_set and field_value is None:
                raise ValueError(f"{field_name} cannot be null.")

        return self


class GoalResponse(GoalBase):
    """
    Schema for returning financial goal data.

    What:
        Defines the public API response shape for goals.

    Why:
        Keeps the database model separated from the API contract.
        current_amount is read-only and ledger-derived (VF-016G): it is
        computed from the goal_transactions ledger at read time
        (opening_balance + contribution - withdrawal) every time a Goal is
        returned, never accepted as client input, and never persisted on
        the Goal row itself. Overfunding is a valid product state (VF-016),
        so current_amount is allowed to exceed target_amount - only
        non-negativity is enforced (a withdrawal can never take the ledger
        balance below zero, see goal_service.create_goal_transaction).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID

    current_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "Amount currently saved for the goal, computed from the "
            "goal_transactions ledger. Read-only. May exceed target_amount."
        ),
        examples=["500.00"],
    )

    created_at: datetime
    updated_at: datetime