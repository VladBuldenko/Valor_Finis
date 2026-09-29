from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountTransactionCreate(BaseModel):
    """
    Schema for creating a new account transaction through the public API.

    What:
        Validates a client-submitted manual adjustment request. VF-017B
        exposes exactly one client-creatable kind: adjustment.

    Why:
        opening_balance must never be reachable through this endpoint - it
        is created exactly once, atomically with the Account row, via
        AccountCreate.opening_balance (see account_service.create_account).
        This schema has no kind field at all: the service always creates
        kind="adjustment" for every row this schema produces, so there is
        no client input to validate or reject for it.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Literal["credit", "debit"] = Field(
        ...,
        description="Whether this adjustment increases or decreases the balance.",
        examples=["credit"],
    )

    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Transaction amount. Always positive; direction comes from direction.",
        examples=["50.00"],
    )

    transaction_date: Date = Field(
        ...,
        description="Date this adjustment actually happened.",
        examples=["2026-09-23"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional free-text note.",
        examples=["Bank fee correction"],
    )


class AccountTransactionResponse(BaseModel):
    """
    Schema for returning account transaction data.

    What:
        Defines the public API response shape for an account transaction.

    Why:
        The kind Literal here is deliberately wider than
        AccountTransactionCreate's (which has no kind field at all): GET
        history must be able to represent the opening_balance row created
        at account creation, the income row created by linking an Income
        (VF-017D), the expense row created by linking an Expense
        (VF-017E), and the transfer rows of a posted AccountTransfer
        (VF-018B), even though clients can never create any of these
        directly through this API. "transfer" is accepted here before any
        public endpoint can create such a row, so history responses can
        never fail validation once one exists. Widening this Literal is
        additive at the type level, but callers that switch exhaustively on kind must
        still be updated to tolerate each new value - it is not claimed
        to be a transparent, zero-effort change for every possible
        client.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    user_id: UUID

    kind: Literal["opening_balance", "adjustment", "income", "expense", "transfer"] = Field(
        description="What kind of ledger event this row represents.",
        examples=["adjustment"],
    )

    direction: Literal["credit", "debit"] = Field(
        description="Whether this transaction increased or decreased the balance.",
        examples=["credit"],
    )

    amount: Decimal = Field(
        max_digits=12,
        decimal_places=2,
        description="Transaction amount. Always positive; direction comes from direction.",
        examples=["50.00"],
    )

    transaction_date: Date = Field(
        description="Date this transaction actually happened.",
        examples=["2026-09-23"],
    )

    description: Optional[str] = Field(
        default=None,
        description="Optional free-text note.",
        examples=["Bank fee correction"],
    )

    income_id: Optional[UUID] = Field(
        default=None,
        description=(
            "If this row is a synchronized Income projection (kind="
            "\"income\"), the source Income's id. Null for direct "
            "opening_balance/adjustment rows and for expense-backed rows."
        ),
        examples=[None],
    )

    expense_id: Optional[UUID] = Field(
        default=None,
        description=(
            "If this row is a synchronized Expense projection (kind="
            "\"expense\"), the source Expense's id. Null for direct "
            "opening_balance/adjustment rows and for income-backed rows."
        ),
        examples=[None],
    )

    transfer_id: Optional[UUID] = Field(
        default=None,
        description=(
            "If this row is one of the two projections of a posted "
            "AccountTransfer (kind=\"transfer\"), the source transfer's id. "
            "Null for every other kind."
        ),
        examples=[None],
    )

    counterparty_account_id: Optional[UUID] = Field(
        default=None,
        description=(
            "For a transfer row (VF-018C), the other Account of the "
            "transfer: the destination Account on the source Account's "
            "debit row, the source Account on the destination Account's "
            "credit row. A read-model value derived from the canonical "
            "transfer, never stored. Null for every other kind."
        ),
        examples=[None],
    )

    created_at: datetime
