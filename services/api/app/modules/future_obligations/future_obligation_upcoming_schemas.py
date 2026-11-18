from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Upcoming bills projection (VF-GOALS-PLANNING-002C1): read-only. It lists what the
# user's own active obligations say will fall due, month by month for a bounded
# window. It is NOT compared with, or subtracted from, historical net flow:
# recorded Expenses may already contain earlier payments of the same bills, so
# any reconciliation needs its own explicit contract (a later task).


class UpcomingOccurrence(BaseModel):
    """One due date of one obligation inside the window."""

    obligation_id: UUID
    name: str
    schedule: Literal["one_time", "monthly"]
    due_date: date
    amount: Decimal
    currency: str


class CurrencyTotal(BaseModel):
    """The exact sum of the occurrences in one currency."""

    currency: str
    total: Decimal
    occurrence_count: int = Field(ge=0)


class UpcomingMonth(BaseModel):
    """One calendar month of the window."""

    period_start: date
    period_end: date
    occurrence_count: int = Field(ge=0, description="Due dates in this month, all currencies.")
    base_currency_total: Decimal = Field(
        description="Sum of this month's occurrences in the base currency only (0.00 when none).",
    )
    totals_by_currency: list[CurrencyTotal] = Field(
        description="One entry per currency with an occurrence this month, sorted by currency.",
    )
    occurrences: list[UpcomingOccurrence] = Field(
        description="Itemized due dates, ordered by due_date, then name, then id.",
    )


class UpcomingObligationsResponse(BaseModel):
    """
    Read-only projection of upcoming bills for a bounded window.

    What:
        HORIZON months starting with the current one. For the current month only
        due dates on or after the server date are included; later months include
        every due date in the month. Only ACTIVE obligations contribute.

    Why:
        Different currencies are never added together or converted: every month
        carries a per-currency breakdown, and base_currency_total adds only the
        base-currency occurrences. When another currency appears in the window,
        excluded_currencies lists it and is_base_total_complete is false, so a
        base total is never mistaken for the whole. These are the user's own
        expected obligations; nothing is paid, reserved or recorded as an Expense,
        and no free-cash or affordability figure is derived from them.
    """

    as_of: date = Field(description="The server date the projection was worked out for.")
    base_currency: str
    horizon_months: int
    window_start: date = Field(description="First day of the current month.")
    window_end: date = Field(description="Last day of the last month of the window.")
    is_base_total_complete: bool = Field(
        description="False when occurrences in another currency fall in the window.",
    )
    excluded_currencies: list[str] = Field(
        description="Currencies other than the base currency that have an occurrence in the window, sorted.",
    )
    base_currency_window_total: Decimal = Field(description="Sum of the base-currency occurrences of the whole window.")
    totals_by_currency: list[CurrencyTotal] = Field(description="Whole-window totals per currency, sorted by currency.")
    months: list[UpcomingMonth] = Field(description="Exactly horizon_months months, current month first.")
