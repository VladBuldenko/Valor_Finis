from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccountTransferCreate(BaseModel):
    """
    Schema for creating an AccountTransfer through the public API (VF-018C).

    What:
        Validates a client-submitted transfer between two of the
        authenticated user's Accounts.

    Why:
        The client sends exactly one date, transfer_date; the service
        classifies it against the server date into an immediately posted
        transfer (today or earlier, effective_date) or a planned one (later,
        planned_date). Every other lifecycle field - status, planned_date,
        effective_date, posted_at - and currency (derived from the Accounts)
        and user_id (from authentication) are server-owned, so extra="forbid"
        rejects them outright. client_request_id is required: it is the
        server-side create idempotency key. description is compared as-is
        for idempotent replays, so it is deliberately not normalized here.
    """

    model_config = ConfigDict(extra="forbid")

    client_request_id: UUID = Field(
        ...,
        description=(
            "Client-generated idempotency key, one per create confirmation "
            "flow and reused for retries of that flow."
        ),
        examples=["0f8c5f5e-6a38-4a8e-9b0e-2f7d0a6f1c11"],
    )

    source_account_id: UUID = Field(
        ...,
        description="Account the money leaves.",
    )

    destination_account_id: UUID = Field(
        ...,
        description="Account the money enters. Must differ from source_account_id.",
    )

    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Transfer amount in the Accounts' shared currency.",
        examples=["300.00"],
    )

    transfer_date: Date = Field(
        ...,
        description=(
            "Date of the transfer. Today or earlier (server date) creates an "
            "immediately posted transfer; a later date creates a planned one."
        ),
        examples=["2026-10-15"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional free-text note.",
        examples=["Move to savings"],
    )

    @model_validator(mode="after")
    def validate_distinct_accounts(self) -> "AccountTransferCreate":
        """
        Rejects a transfer from an Account to itself.

        What:
            Checks that source_account_id and destination_account_id differ.

        Why:
            A transfer to the same Account has no financial meaning; the
            database also rejects it (ck_account_transfers_distinct_accounts)
            as the last line of defense.
        """
        if self.source_account_id == self.destination_account_id:
            raise ValueError("source_account_id and destination_account_id must differ.")

        return self


class AccountTransferResponse(BaseModel):
    """
    Schema for returning AccountTransfer data (VF-018C).

    What:
        Defines the public API response shape for a planned or posted
        transfer.

    Why:
        Exposes the lifecycle exactly as stored: planned_date is set only
        for a transfer created as planned (and stays set after posting),
        effective_date and posted_at only once posted. There is no
        transfer_date field - that exists only on the create request.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    client_request_id: UUID
    source_account_id: UUID
    destination_account_id: UUID

    amount: Decimal = Field(
        max_digits=12,
        decimal_places=2,
        examples=["300.00"],
    )

    currency: str = Field(examples=["EUR"])

    status: Literal["planned", "posted"] = Field(
        description="planned: expected, no ledger effect; posted: reflected in both Accounts' ledgers.",
        examples=["posted"],
    )

    planned_date: Optional[Date] = Field(
        default=None,
        description="Original expected date; set only for a transfer created as planned.",
    )

    effective_date: Optional[Date] = Field(
        default=None,
        description="Accounting date the money moved; set once posted.",
    )

    description: Optional[str] = None

    posted_at: Optional[datetime] = Field(
        default=None,
        description="Technical timestamp of the change to posted.",
    )

    created_at: datetime
    updated_at: datetime
