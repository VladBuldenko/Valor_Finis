from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Sequence

from app.modules.future_obligations.future_obligation_models import FutureObligationModel
from app.modules.future_obligations.future_obligation_schedule import (
    due_date_in_month,
    month_index,
    year_and_month,
)
from app.modules.future_obligations.future_obligation_upcoming_schemas import (
    CurrencyTotal,
    UpcomingMonth,
    UpcomingObligationsResponse,
    UpcomingOccurrence,
)

# Upcoming bills projection (VF-GOALS-PLANNING-002C1): pure, deterministic arithmetic
# with no database, clock or HTTP access.
#
# THE RULES
# - The window is HORIZON_MONTHS calendar months starting with the month of
#   `as_of` (the server date).
# - Every month's due dates come straight from the recurrence rules
#   (future_obligation_schedule), so nothing is stepped from a previous date.
# - In the CURRENT month only due dates on or after `as_of` count (earlier ones
#   are in the past); later months include every due date in the month.
# - Only ACTIVE obligations contribute; an archived one is ignored here even if
#   the caller passes it.
# - Money is exact Decimal (amounts already have 2 decimal places). Currencies
#   are NEVER added together or converted: each month has a per-currency
#   breakdown, and the base-currency total adds the base-currency occurrences
#   only. Other currencies are reported, and the base total flagged incomplete.
# - The projection is an independent forecast input. It is not compared with or
#   subtracted from historical net flow, which already contains recorded
#   Expenses, and it implies no paid status, reservation or Expense.

HORIZON_MONTHS = 12

_ZERO = Decimal("0.00")


# The last day of the projection window that starts in the month of `as_of`.
# Shared by the repository query bound and the builder, so they cannot disagree.
def window_end_for(as_of: date) -> date:
    year, month = year_and_month(month_index(as_of.year, as_of.month) + HORIZON_MONTHS)

    return date(year, month, 1) - timedelta(days=1)


# Builds the response from the user's obligations.
# Parameters:
# - obligations: the user's obligations (any status; only active ones count).
# - base_currency: the user's base currency.
# - as_of: the server date.
# Returns:
# - UpcomingObligationsResponse.
def build_upcoming_obligations(
    obligations: Sequence[FutureObligationModel],
    base_currency: str,
    as_of: date,
) -> UpcomingObligationsResponse:
    active = [obligation for obligation in obligations if obligation.status == "active"]
    first_index = month_index(as_of.year, as_of.month)

    months: list[UpcomingMonth] = []
    window_totals: Dict[str, Decimal] = {}
    window_counts: Dict[str, int] = {}

    for offset in range(HORIZON_MONTHS):
        year, month = year_and_month(first_index + offset)
        period_start = date(year, month, 1)
        next_year, next_month = year_and_month(first_index + offset + 1)
        period_end = date(next_year, next_month, 1) - timedelta(days=1)

        occurrences: list[UpcomingOccurrence] = []

        for obligation in active:
            due_date = due_date_in_month(
                obligation.schedule,
                obligation.first_due_date,
                obligation.final_due_date,
                year,
                month,
            )

            if due_date is None or due_date < as_of:
                continue

            occurrences.append(
                UpcomingOccurrence(
                    obligation_id=obligation.id,
                    name=obligation.name,
                    schedule=obligation.schedule,
                    due_date=due_date,
                    amount=obligation.amount,
                    currency=obligation.currency,
                )
            )

        occurrences.sort(key=lambda item: (item.due_date, item.name, str(item.obligation_id)))

        month_totals: Dict[str, Decimal] = {}
        month_counts: Dict[str, int] = {}

        for item in occurrences:
            month_totals[item.currency] = month_totals.get(item.currency, _ZERO) + item.amount
            month_counts[item.currency] = month_counts.get(item.currency, 0) + 1
            window_totals[item.currency] = window_totals.get(item.currency, _ZERO) + item.amount
            window_counts[item.currency] = window_counts.get(item.currency, 0) + 1

        months.append(
            UpcomingMonth(
                period_start=period_start,
                period_end=period_end,
                occurrence_count=len(occurrences),
                base_currency_total=month_totals.get(base_currency, _ZERO),
                totals_by_currency=[
                    CurrencyTotal(currency=code, total=month_totals[code], occurrence_count=month_counts[code])
                    for code in sorted(month_totals)
                ],
                occurrences=occurrences,
            )
        )

    excluded = sorted(code for code in window_totals if code != base_currency)

    return UpcomingObligationsResponse(
        as_of=as_of,
        base_currency=base_currency,
        horizon_months=HORIZON_MONTHS,
        window_start=months[0].period_start,
        window_end=months[-1].period_end,
        is_base_total_complete=not excluded,
        excluded_currencies=excluded,
        base_currency_window_total=window_totals.get(base_currency, _ZERO),
        totals_by_currency=[
            CurrencyTotal(currency=code, total=window_totals[code], occurrence_count=window_counts[code])
            for code in sorted(window_totals)
        ],
        months=months,
    )
