from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import create_idempotency
from app.modules.financial_settings import financial_settings_service
from app.modules.future_obligations import future_obligation_link_service, future_obligation_repository
from app.modules.future_obligations.future_obligation_errors import (
    FutureObligationClientRequestIdTakenError,
    FutureObligationIdempotencyConflictError,
    FutureObligationLimitReachedError,
    FutureObligationNotFoundError,
    FutureObligationScheduleInvalidError,
)
from app.modules.future_obligations.future_obligation_models import FutureObligationModel
from app.modules.future_obligations.future_obligation_projection import (
    build_upcoming_obligations,
    window_end_for,
)
from app.modules.future_obligations.future_obligation_schedule import (
    next_due_date,
    schedule_shape_error,
)
from app.modules.future_obligations.future_obligation_schemas import (
    FutureObligationCreate,
    FutureObligationResponse,
    FutureObligationUpdate,
)
from app.modules.future_obligations.future_obligation_upcoming_schemas import (
    UpcomingObligationsResponse,
)

# Future obligations (VF-GOALS-PLANNING-002C1): the service layer.
#
# An obligation is an independent forecast input the user typed in. Nothing in
# this module creates an Expense, an Account transaction, a Goal transaction, a
# reservation or a financial event, and nothing reads them: it is a separate
# domain, so a bill is never counted twice against recorded history.

# The most ACTIVE obligations one user may have. The projection reads and
# calculates every active obligation on each request, so the count is bounded;
# archived obligations do not count.
MAX_ACTIVE_OBLIGATIONS = 200

AMOUNT_PLACES = Decimal("0.01")

CREATE_OPERATION = "future_obligations.create"
ACTIVE_LIMIT_LOCK_OPERATION = "future_obligations.active_limit"


# Builds the public representation of an obligation, with its next due date as of
# `today`. An archived obligation has none.
def _build_response(obligation: FutureObligationModel, today: date) -> FutureObligationResponse:
    response = FutureObligationResponse.model_validate(obligation)

    if obligation.status != "active":
        return response

    return response.model_copy(
        update={
            "next_due_date": next_due_date(
                obligation.schedule,
                obligation.first_due_date,
                obligation.final_due_date,
                today,
            )
        }
    )


# Serializes every change that can raise the number of one user's active
# obligations (a create, or restoring an archived one) for the rest of the
# transaction, so the limit cannot be exceeded by two concurrent requests. It is
# a transaction-scoped advisory lock: the commit or rollback releases it, and it
# never locks a row or blocks another user.
def _lock_active_limit(db_session: Session, user_id: UUID) -> None:
    db_session.execute(
        text(create_idempotency.ADVISORY_LOCK_SQL),
        {
            "lock_key": create_idempotency.compute_create_key_lock_key(
                ACTIVE_LIMIT_LOCK_OPERATION, user_id, user_id
            )
        },
    )


# Raises FutureObligationLimitReachedError when the user is at the limit. Callers
# hold the active-limit lock.
def _ensure_room_for_one_more_active(db_session: Session, user_id: UUID) -> None:
    if future_obligation_repository.count_active_for_user(db_session, user_id) >= MAX_ACTIVE_OBLIGATIONS:
        raise FutureObligationLimitReachedError()


# The canonical fingerprint of a create request: the single definition of "same
# request" for create idempotency. Money is a fixed two-decimal string, dates are
# ISO strings, and the currency is the RESOLVED one (an omitted currency and the
# base currency written out are the same request). client_request_id and the
# user are the lookup scope, not part of it.
def _request_fingerprint(data: FutureObligationCreate, currency: str) -> str:
    return create_idempotency.compute_request_fingerprint(
        CREATE_OPERATION,
        {
            "name": data.name,
            "description": data.description,
            "schedule": data.schedule,
            "amount": format(data.amount.quantize(AMOUNT_PLACES), "f"),
            "currency": currency,
            "first_due_date": data.first_due_date.isoformat(),
            "final_due_date": data.final_due_date.isoformat() if data.final_due_date is not None else None,
        },
    )


@dataclass(frozen=True)
class FutureObligationCreateResult:
    """
    Outcome of create_or_replay_future_obligation.

    Fields:
        obligation: the obligation's public representation (its CURRENT state on
            a replay).
        created: True when this call created it, False for an idempotent replay.
            POST answers 201 or 200 accordingly.
    """

    obligation: FutureObligationResponse
    created: bool


# Resolves a create whose client_request_id already identifies a stored
# obligation: a replay when the fingerprint matches, a conflict otherwise. It
# writes nothing.
def _resolve_existing(
    obligation: FutureObligationModel,
    fingerprint: str,
    today: date,
) -> FutureObligationCreateResult:
    if obligation.client_request_fingerprint != fingerprint:
        raise FutureObligationIdempotencyConflictError()

    return FutureObligationCreateResult(obligation=_build_response(obligation, today), created=False)


# Records a future obligation.
# This function exists to let the user enter a bill they expect to owe. With no
# client_request_id every call creates a record; with one, a retry of the same
# request returns the original (nothing is created twice) and the same key with
# a different request is a conflict. The record, its key and the commit are one
# transaction. currency defaults to the user's base currency through the
# read-only settings lookup (no settings row is created). Nothing is converted,
# and no Expense, Account or Goal row is touched.
# Parameters:
# - data: the validated create request.
# - user_id: the authenticated user.
# - as_of: optional server date (defaults to today), used for next_due_date.
# Raises:
# - FutureObligationLimitReachedError: the user already has the maximum of
#   active obligations.
# - FutureObligationIdempotencyConflictError: the key belongs to another request.
def create_or_replay_future_obligation(
    db_session: Session,
    data: FutureObligationCreate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> FutureObligationCreateResult:
    today = as_of if as_of is not None else date.today()
    currency = data.currency or financial_settings_service.get_base_currency_read_only(
        db_session=db_session,
        user_id=user_id,
    )
    fingerprint = _request_fingerprint(data, currency)
    client_request_id = data.client_request_id

    if client_request_id is not None:
        create_idempotency.acquire_create_key_lock(db_session, CREATE_OPERATION, user_id, client_request_id)

        existing = future_obligation_repository.get_by_client_request_id(db_session, user_id, client_request_id)

        if existing is not None:
            try:
                return _resolve_existing(existing, fingerprint, today)
            finally:
                # Nothing was written; release the key lock.
                db_session.rollback()

    try:
        _lock_active_limit(db_session, user_id)
        _ensure_room_for_one_more_active(db_session, user_id)

        created = future_obligation_repository.create_obligation(
            db_session=db_session,
            data=data,
            currency=currency,
            user_id=user_id,
            commit=False,
            client_request_fingerprint=fingerprint if client_request_id is not None else None,
        )
        db_session.commit()
        db_session.refresh(created)

        return FutureObligationCreateResult(obligation=_build_response(created, today), created=True)
    except FutureObligationClientRequestIdTakenError:
        db_session.rollback()

        winner = (
            future_obligation_repository.get_by_client_request_id(db_session, user_id, client_request_id)
            if client_request_id is not None
            else None
        )

        if winner is None:
            # The unique violation proves a same-key record committed, so failing
            # to reload it is unexpected: never fabricate a result.
            raise

        try:
            return _resolve_existing(winner, fingerprint, today)
        finally:
            db_session.rollback()
    except Exception:
        db_session.rollback()
        raise


# Returns one obligation of the user.
# Raises:
# - FutureObligationNotFoundError: it does not exist or is not the user's.
def get_future_obligation(
    db_session: Session,
    obligation_id: UUID,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> FutureObligationResponse:
    obligation = future_obligation_repository.get_by_id(db_session, obligation_id, user_id)

    if obligation is None:
        raise FutureObligationNotFoundError()

    return _build_response(obligation, as_of if as_of is not None else date.today())


# Returns every obligation of the user, active ones first by their next due date
# (those with none left after), then archived ones. One query, no writes.
def get_future_obligations(
    db_session: Session,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> list[FutureObligationResponse]:
    today = as_of if as_of is not None else date.today()
    responses = [
        _build_response(obligation, today)
        for obligation in future_obligation_repository.list_for_user(db_session, user_id)
    ]

    return sorted(
        responses,
        key=lambda item: (
            item.status != "active",
            item.next_due_date is None,
            item.next_due_date or date.max,
            item.name,
            str(item.id),
        ),
    )


# Updates (or archives or restores) an obligation of the user.
# This function exists so a bill can be corrected or retired. The row is locked
# for the change, the schedule fields are validated as the RESULTING state, and
# archiving or restoring takes effect on the very next projection. The schedule
# kind is not editable. Nothing else is touched.
# Raises:
# - FutureObligationNotFoundError: it does not exist or is not the user's.
# - FutureObligationScheduleInvalidError: the resulting dates are not valid.
# - FutureObligationLimitReachedError: restoring it would exceed the active limit.
def update_future_obligation(
    db_session: Session,
    obligation_id: UUID,
    data: FutureObligationUpdate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> FutureObligationResponse:
    today = as_of if as_of is not None else date.today()

    try:
        obligation = future_obligation_repository.get_by_id_for_update(db_session, obligation_id, user_id)

        if obligation is None:
            raise FutureObligationNotFoundError()

        fields = data.model_fields_set
        first_due_date = data.first_due_date if "first_due_date" in fields else obligation.first_due_date
        final_due_date = data.final_due_date if "final_due_date" in fields else obligation.final_due_date

        if schedule_shape_error(obligation.schedule, first_due_date, final_due_date) is not None:
            raise FutureObligationScheduleInvalidError()

        # VF-GOALS-PLANNING-002C2: a linked occurrence must stay valid. The amount,
        # the currency and the dates are checked against its links under the row
        # lock (a link is created under that same lock); other edits, archiving
        # and restoring are never blocked and no link is ever deleted here.
        future_obligation_link_service.ensure_obligation_change_allowed(
            db_session=db_session,
            user_id=user_id,
            obligation=obligation,
            final_amount=data.amount if "amount" in fields and data.amount is not None else obligation.amount,
            final_currency=data.currency if "currency" in fields and data.currency is not None else obligation.currency,
            final_first_due_date=first_due_date,
            final_final_due_date=final_due_date,
        )

        if "status" in fields and data.status == "active" and obligation.status != "active":
            _lock_active_limit(db_session, user_id)
            _ensure_room_for_one_more_active(db_session, user_id)

        if "name" in fields and data.name is not None:
            obligation.name = data.name

        if "description" in fields:
            obligation.description = data.description

        if "amount" in fields and data.amount is not None:
            obligation.amount = data.amount

        if "currency" in fields and data.currency is not None:
            obligation.currency = data.currency

        obligation.first_due_date = first_due_date
        obligation.final_due_date = final_due_date

        if "status" in fields and data.status is not None:
            obligation.status = data.status

        db_session.commit()
        db_session.refresh(obligation)

        return _build_response(obligation, today)
    except Exception:
        db_session.rollback()
        raise


# Projects the user's upcoming bills for the next 12 calendar months, including
# the current one, as of the server date. Read-only: one bounded query over the
# user's active obligations, the base currency read without the first-use
# settings write, and exact Decimal sums per currency. Nothing is stored, paid,
# reserved or recorded as an Expense, and nothing is subtracted from history.
def get_upcoming_obligations(
    db_session: Session,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> UpcomingObligationsResponse:
    today = as_of if as_of is not None else date.today()
    base_currency = financial_settings_service.get_base_currency_read_only(
        db_session=db_session,
        user_id=user_id,
    )
    obligations = future_obligation_repository.list_active_for_projection(
        db_session=db_session,
        user_id=user_id,
        as_of=today,
        window_end=window_end_for(today),
    )

    return build_upcoming_obligations(obligations, base_currency, today)
