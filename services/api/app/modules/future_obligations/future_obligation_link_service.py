from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.future_obligations import (
    future_obligation_link_repository as link_repository,
    future_obligation_repository,
)
from app.modules.future_obligations.future_obligation_errors import (
    ExpenseLinkedToFutureObligationError,
    FutureObligationHasLinkedOccurrencesError,
    FutureObligationLinkAmountMismatchError,
    FutureObligationLinkCurrencyMismatchError,
    FutureObligationLinkExpenseAlreadyLinkedError,
    FutureObligationLinkExpenseDateError,
    FutureObligationLinkNotFoundError,
    FutureObligationLinkOccurrenceAlreadyLinkedError,
    FutureObligationLinkUniqueViolationError,
    FutureObligationNotFoundError,
    FutureObligationOccurrenceInvalidError,
)
from app.modules.future_obligations.future_obligation_link_models import (
    UNIQUE_EXPENSE_CONSTRAINT,
    FutureObligationExpenseLinkModel,
)
from app.modules.future_obligations.future_obligation_link_schemas import (
    CandidateExclusions,
    CandidateExpense,
    LinkedExpenseSummary,
    OccurrenceCandidatesResponse,
    OccurrenceLinkCreate,
    OccurrenceLinkResponse,
    ReconciliationOccurrence,
    ReconciliationOverviewResponse,
)
from app.modules.future_obligations.future_obligation_models import FutureObligationModel
from app.modules.future_obligations.future_obligation_projection import window_end_for
from app.modules.future_obligations.future_obligation_schedule import (
    due_date_in_month,
    month_index,
    year_and_month,
)

# Manual reconciliation (VF-GOALS-PLANNING-002C2): the service layer.
#
# A link says "this recorded Expense corresponds to this bill occurrence". It is
# relationship metadata the user chose. Nothing here creates or changes an Expense,
# posts to an Account, touches a Goal or a rule, or says a bank payment was
# verified, and nothing is ever matched automatically.
#
# LOCK ORDER (the only one used anywhere): the Expense row first, then the
# obligation row. This is the order Expense update/delete already use (the Expense
# is locked before anything it relates to), and no code path takes the obligation
# lock and then an Expense lock, so reconciliation cannot deadlock with Expense or
# obligation edits. The guards below run under the caller's own row lock, so a
# concurrent link cannot slip in between a guard's check and its write.

# How many Expenses the picker returns (newest first).
CANDIDATE_LIMIT = 50

# The overview reaches this many completed calendar months back, in addition to the
# current month and the 12-month planning horizon.
PAST_MONTHS = 3


@dataclass(frozen=True)
class OccurrenceLinkResult:
    """
    Outcome of create_or_replay_link.

    Fields:
        link: the stored link.
        created: True when this call created it, False for an idempotent replay.
            POST answers 201 or 200 accordingly.
    """

    link: OccurrenceLinkResponse
    created: bool


def _today(as_of: Optional[date]) -> date:
    return as_of if as_of is not None else date.today()


# True when `due_date` is exactly an occurrence of the given schedule: a monthly due
# date must be the (clamped) anchor day of its month, so Feb 28 is an occurrence of
# a "31st" bill and Feb 27 or Feb 30 are not.
def is_scheduled_occurrence(
    schedule: str,
    first_due_date: date,
    final_due_date: Optional[date],
    due_date: date,
) -> bool:
    return (
        due_date_in_month(schedule, first_due_date, final_due_date, due_date.year, due_date.month)
        == due_date
    )


# Raises FutureObligationOccurrenceInvalidError unless the obligation is active and
# `due_date` is on its schedule.
def _ensure_valid_occurrence(obligation: FutureObligationModel, due_date: date) -> None:
    if obligation.status != "active" or not is_scheduled_occurrence(
        obligation.schedule,
        obligation.first_due_date,
        obligation.final_due_date,
        due_date,
    ):
        raise FutureObligationOccurrenceInvalidError()


# Validates an Expense against an occurrence: exact currency, exact Decimal amount
# and a recorded date that is not after `today`. Checked in this order.
def _ensure_expense_matches(obligation: FutureObligationModel, expense: ExpenseModel, today: date) -> None:
    if expense.currency != obligation.currency:
        raise FutureObligationLinkCurrencyMismatchError()

    if expense.amount != obligation.amount:
        raise FutureObligationLinkAmountMismatchError()

    if expense.expense_date > today:
        raise FutureObligationLinkExpenseDateError()


# Links one occurrence of an obligation to an existing Expense of the user, or
# replays an identical earlier link.
# Locks the Expense, then the obligation (see LOCK ORDER) and validates everything
# against the locked rows, so a concurrent Expense or obligation edit cannot make
# the check stale. A repeat of the SAME (occurrence, Expense) returns the existing
# link and writes nothing. A link is never replaced: another Expense for the same
# occurrence, or the same Expense for another occurrence, is a conflict. The
# response is built before the commit, while the locks are held.
# Parameters:
# - obligation_id: the obligation (from the path).
# - data: the validated request (due_date, expense_id).
# - user_id: the authenticated user.
# - as_of: optional server date (defaults to today).
# Raises:
# - ExpenseNotFoundError / FutureObligationNotFoundError: missing or not the user's.
# - FutureObligationLinkOccurrenceAlreadyLinkedError / ...ExpenseAlreadyLinkedError.
# - FutureObligationOccurrenceInvalidError, ...CurrencyMismatchError,
#   ...AmountMismatchError, ...ExpenseDateError: the Expense cannot be linked.
def create_or_replay_link(
    db_session: Session,
    obligation_id: UUID,
    data: OccurrenceLinkCreate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> OccurrenceLinkResult:
    today = _today(as_of)

    try:
        expense = expenses_repository.get_expense_by_id_for_update(db_session, data.expense_id, user_id)
        obligation = future_obligation_repository.get_by_id_for_update(db_session, obligation_id, user_id)

        if obligation is None:
            raise FutureObligationNotFoundError()

        occurrence_link = link_repository.get_by_occurrence(db_session, user_id, obligation.id, data.due_date)

        if occurrence_link is not None:
            if occurrence_link.expense_id != expense.id:
                raise FutureObligationLinkOccurrenceAlreadyLinkedError()

            replay = OccurrenceLinkResponse.model_validate(occurrence_link)
            db_session.rollback()

            return OccurrenceLinkResult(link=replay, created=False)

        if link_repository.get_by_expense(db_session, user_id, expense.id) is not None:
            raise FutureObligationLinkExpenseAlreadyLinkedError()

        _ensure_valid_occurrence(obligation, data.due_date)
        _ensure_expense_matches(obligation, expense, today)

        created = link_repository.create_link(db_session, user_id, obligation.id, data.due_date, expense.id)
        response = OccurrenceLinkResponse.model_validate(created)
        db_session.commit()

        return OccurrenceLinkResult(link=response, created=True)
    except FutureObligationLinkUniqueViolationError as error:
        # Unreachable while both locks are held, but the unique keys are the final
        # backstop: report the rule that was violated, never a 500.
        db_session.rollback()

        if error.constraint_name == UNIQUE_EXPENSE_CONSTRAINT:
            raise FutureObligationLinkExpenseAlreadyLinkedError() from error

        raise FutureObligationLinkOccurrenceAlreadyLinkedError() from error
    except Exception:
        db_session.rollback()
        raise


# Removes a link. The Expense and the obligation are left exactly as they were.
# Raises:
# - FutureObligationLinkNotFoundError: no such link of the user's on that obligation.
def delete_link(
    db_session: Session,
    obligation_id: UUID,
    link_id: UUID,
    user_id: UUID,
) -> None:
    try:
        link = link_repository.get_by_id(db_session, link_id, user_id, for_update=True)

        if link is None or link.obligation_id != obligation_id:
            raise FutureObligationLinkNotFoundError()

        link_repository.delete_link(db_session, link)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def _linked_summary(link: FutureObligationExpenseLinkModel, expense: ExpenseModel) -> LinkedExpenseSummary:
    return LinkedExpenseSummary(
        link_id=link.id,
        expense_id=expense.id,
        title=expense.title,
        expense_date=expense.expense_date,
        amount=expense.amount,
        currency=expense.currency,
        linked_at=link.created_at,
    )


# The first day of the overview window: the month `PAST_MONTHS` before today's.
def window_start_for(as_of: date) -> date:
    year, month = year_and_month(month_index(as_of.year, as_of.month) - PAST_MONTHS)

    return date(year, month, 1)


# Builds the bounded, read-only overview of occurrences and their link status.
# Active obligations contribute their scheduled occurrences in the window; an
# archived obligation contributes only occurrences that already have a link, so
# archiving never erases history. The Upcoming Bills projection is not touched and
# nothing is subtracted from it.
def get_overview(
    db_session: Session,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> ReconciliationOverviewResponse:
    today = _today(as_of)
    window_start = window_start_for(today)
    window_end = window_end_for(today)

    obligations = {
        obligation.id: obligation
        for obligation in future_obligation_repository.list_active_for_window(
            db_session, user_id, window_start, window_end
        )
    }
    linked = {
        (link.obligation_id, link.due_date): (link, expense)
        for link, expense in link_repository.list_in_window_with_expenses(
            db_session, user_id, window_start, window_end
        )
    }

    missing_ids = sorted({obligation_id for obligation_id, _ in linked} - set(obligations), key=str)

    for obligation in future_obligation_repository.list_by_ids(db_session, user_id, missing_ids):
        obligations[obligation.id] = obligation

    first_index = month_index(window_start.year, window_start.month)
    last_index = month_index(window_end.year, window_end.month)
    entries: dict[tuple[UUID, date], FutureObligationModel] = {}

    for obligation in obligations.values():
        if obligation.status != "active":
            continue

        for index in range(first_index, last_index + 1):
            year, month = year_and_month(index)
            due_date = due_date_in_month(
                obligation.schedule, obligation.first_due_date, obligation.final_due_date, year, month
            )

            if due_date is not None:
                entries[(obligation.id, due_date)] = obligation

    for obligation_id, due_date in linked:
        entries[(obligation_id, due_date)] = obligations[obligation_id]

    occurrences = [
        ReconciliationOccurrence(
            obligation_id=obligation.id,
            name=obligation.name,
            schedule=obligation.schedule,
            obligation_status=obligation.status,
            due_date=due_date,
            amount=obligation.amount,
            currency=obligation.currency,
            is_past=due_date < today,
            linked_expense=_linked_summary(*linked[(obligation.id, due_date)])
            if (obligation.id, due_date) in linked
            else None,
        )
        for (_, due_date), obligation in entries.items()
    ]
    occurrences.sort(key=lambda item: (item.due_date, item.name, str(item.obligation_id)))

    return ReconciliationOverviewResponse(
        as_of=today,
        window_start=window_start,
        window_end=window_end,
        occurrences=occurrences,
    )


# The Expenses the user may link to one occurrence, plus a count of the other
# Expenses that cannot be linked and why. Read-only; the user chooses, nothing is
# matched by name or by any guess.
# Raises:
# - FutureObligationNotFoundError / FutureObligationOccurrenceInvalidError.
def get_candidates(
    db_session: Session,
    obligation_id: UUID,
    due_date: date,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> OccurrenceCandidatesResponse:
    today = _today(as_of)
    obligation = future_obligation_repository.get_by_id(db_session, obligation_id, user_id)

    if obligation is None:
        raise FutureObligationNotFoundError()

    _ensure_valid_occurrence(obligation, due_date)

    candidates = link_repository.list_candidate_expenses(
        db_session, user_id, obligation.currency, obligation.amount, today, CANDIDATE_LIMIT
    )
    excluded = link_repository.count_excluded_expenses(
        db_session, user_id, obligation.currency, obligation.amount, today
    )

    return OccurrenceCandidatesResponse(
        obligation_id=obligation.id,
        due_date=due_date,
        amount=obligation.amount,
        currency=obligation.currency,
        candidate_limit=CANDIDATE_LIMIT,
        candidates=[
            CandidateExpense(
                expense_id=expense.id,
                title=expense.title,
                expense_date=expense.expense_date,
                amount=expense.amount,
                currency=expense.currency,
            )
            for expense in candidates
        ],
        excluded=CandidateExclusions(**excluded),
    )


# --- guards called by the Expense and obligation services --------------------


# Raises ExpenseLinkedToFutureObligationError when the Expense is linked and the
# change would invalidate the link: a different amount, a different currency or a
# recorded date after `today`. Title, description, category, source and Account
# linkage are never blocked. The caller holds the Expense row lock, and a link
# can only be created under that same lock, so the answer cannot go stale.
def ensure_expense_change_allowed(
    db_session: Session,
    user_id: UUID,
    expense: ExpenseModel,
    final_amount: Decimal,
    final_currency: str,
    final_expense_date: date,
    today: date,
) -> None:
    if link_repository.get_by_expense(db_session, user_id, expense.id) is None:
        return

    if (
        final_amount != expense.amount
        or final_currency != expense.currency
        or final_expense_date > today
    ):
        raise ExpenseLinkedToFutureObligationError()


# Raises ExpenseLinkedToFutureObligationError when the Expense is linked. The
# caller holds the Expense row lock.
def ensure_expense_can_be_deleted(db_session: Session, user_id: UUID, expense_id: UUID) -> None:
    if link_repository.get_by_expense(db_session, user_id, expense_id) is not None:
        raise ExpenseLinkedToFutureObligationError()


# Raises FutureObligationHasLinkedOccurrencesError when an edit of the obligation
# would invalidate a linked occurrence: a different amount or currency, or dates
# that no longer put a linked due date on the schedule. Name, description and
# status changes (archive and restore) never come here. The caller holds the
# obligation row lock, and a link can only be created under that same lock.
def ensure_obligation_change_allowed(
    db_session: Session,
    user_id: UUID,
    obligation: FutureObligationModel,
    final_amount: Decimal,
    final_currency: str,
    final_first_due_date: date,
    final_final_due_date: Optional[date],
) -> None:
    links = link_repository.list_for_obligation(db_session, user_id, obligation.id)

    if not links:
        return

    if final_amount != obligation.amount or final_currency != obligation.currency:
        raise FutureObligationHasLinkedOccurrencesError()

    for link in links:
        if not is_scheduled_occurrence(obligation.schedule, final_first_due_date, final_final_due_date, link.due_date):
            raise FutureObligationHasLinkedOccurrencesError()
