from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.future_obligations.future_obligation_schedule import MAX_DUE_DATE, MIN_DUE_DATE

# Manual reconciliation (VF-GOALS-PLANNING-002C2). A link says "this recorded Expense
# corresponds to this bill occurrence". It is relationship metadata: it is not a
# payment, does not verify a bank transaction and moves no money.


class OccurrenceLinkCreate(BaseModel):
    """
    Request to link one occurrence of an obligation to an existing Expense.

    What:
        due_date identifies the occurrence (with the obligation id from the path);
        expense_id names the user's own Expense. Nothing else is accepted: the
        owner comes from authentication, never from the body.
    """

    model_config = ConfigDict(extra="forbid")

    due_date: date
    expense_id: UUID

    @field_validator("due_date")
    @classmethod
    def due_date_in_range(cls, value: date) -> date:
        if value < MIN_DUE_DATE or value > MAX_DUE_DATE:
            raise ValueError("due_date must be between 2000-01-01 and 2100-12-31.")

        return value


class OccurrenceLinkResponse(BaseModel):
    """A stored link."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    obligation_id: UUID
    due_date: date
    expense_id: UUID
    created_at: datetime


class LinkedExpenseSummary(BaseModel):
    """The Expense a link points to, as recorded."""

    link_id: UUID
    expense_id: UUID
    title: str
    expense_date: date
    amount: Decimal
    currency: str
    linked_at: datetime


class ReconciliationOccurrence(BaseModel):
    """One scheduled occurrence and whether an Expense is linked to it."""

    obligation_id: UUID
    name: str
    schedule: Literal["one_time", "monthly"]
    obligation_status: Literal["active", "archived"]
    due_date: date
    amount: Decimal
    currency: str
    is_past: bool = Field(description="True when due_date is before the server date.")
    linked_expense: Optional[LinkedExpenseSummary] = Field(
        description="The linked Expense, or null when none is linked. Null is not a statement that the bill is unpaid.",
    )


class ReconciliationOverviewResponse(BaseModel):
    """
    Read-only, bounded view of occurrences and their link status.

    What:
        The three previous calendar months, the current month and the rest of the
        12-month planning horizon, as of the server date. Active obligations
        contribute their scheduled occurrences; an archived obligation contributes
        only the occurrences that already have a link, so history is kept.

    Why:
        It does not change, replace or subtract from the Upcoming Bills totals or
        from any historical figure, and an occurrence without a link is not a
        confirmed unpaid debt: the user may simply not have recorded the payment.
    """

    as_of: date
    window_start: date = Field(description="First day of the month three months before the current one.")
    window_end: date = Field(description="Last day of the last month of the planning horizon.")
    occurrences: list[ReconciliationOccurrence] = Field(
        description="Ordered by due_date, then name, then obligation id.",
    )


class CandidateExpense(BaseModel):
    """An Expense the user may link to the occurrence."""

    expense_id: UUID
    title: str
    expense_date: date
    amount: Decimal
    currency: str


class CandidateExclusions(BaseModel):
    """
    How many of the user's other Expenses cannot be linked, and why. Every Expense
    falls into exactly one bucket (the first reason that applies, in this order).
    """

    different_currency: int = Field(ge=0)
    different_amount: int = Field(ge=0, description="Same currency, different amount.")
    already_linked: int = Field(ge=0, description="Same currency and amount, linked to an occurrence already.")
    dated_in_future: int = Field(ge=0, description="Same currency and amount, but recorded after the server date.")


class OccurrenceCandidatesResponse(BaseModel):
    """
    The Expenses that can be linked to one occurrence.

    What:
        Only Expenses that pass every rule (same currency, exact same amount, not
        linked yet, recorded on or before the server date), newest first and
        bounded. The user chooses; nothing is matched or ranked by name or by any
        guess, and an amount match is not proof that the records correspond.
    """

    obligation_id: UUID
    due_date: date
    amount: Decimal
    currency: str
    candidate_limit: int
    candidates: list[CandidateExpense]
    excluded: CandidateExclusions
