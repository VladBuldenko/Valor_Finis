from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Union
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.financial_events import financial_event_repository
from app.modules.financial_events.financial_event_models import FinancialEventModel
from app.modules.income.income_models import IncomeModel

AGGREGATE_TYPE_INCOME = "income"

EVENT_INCOME_CREATED = "income.created"
EVENT_INCOME_UPDATED = "income.updated"
EVENT_INCOME_DELETED = "income.deleted"

ORIGIN_MANUAL = "manual"

INGESTION_LIVE = "live"
INGESTION_HISTORICAL = "historical"
INGESTION_CORRECTION = "correction"

# Approved live-entry window (E1 contract P51): a manual Income whose
# received_at is not older than this many days before the server creation
# date is "live"; the boundary day itself is live (inclusive).
LIVE_ENTRY_WINDOW_DAYS = 7


# Returns the server date used for provenance classification and the
# business-date deferral. It is the same server-date semantics as the rest
# of the Income service (date.today(), no client or user timezone). It is a
# separate function so tests can control the date deterministically.
# Parameters:
# - None.
# Returns:
# - The server's current date.
def server_today() -> date:
    return date.today()


# Classifies the provenance mode of a manual Income creation (P51).
# Parameters:
# - received_at: the Income's received_at date.
# - creation_date: the server date on which the Income is created.
# Returns:
# - "live" when received_at >= creation_date - 7 days (future dates included),
#   otherwise "historical".
def classify_manual_creation(received_at: date, creation_date: date) -> str:
    boundary = creation_date - timedelta(days=LIVE_ENTRY_WINDOW_DAYS)

    if received_at >= boundary:
        return INGESTION_LIVE

    return INGESTION_HISTORICAL


# Computes the event's not_before.
# A future-dated Income (received_at after the server date) is deferred to
# the start of its received_at day (UTC midnight, matching the UTC server);
# otherwise not_before is the database "now" of the inserting transaction.
# Parameters:
# - received_at: the Income's received_at date at the event state.
# - today: the server date.
# Returns:
# - A timestamptz value, or func.now() evaluated by the database.
def compute_not_before(
    received_at: date, today: date,
) -> Union[datetime, ColumnElement]:
    if received_at > today:
        return datetime.combine(received_at, time.min, tzinfo=timezone.utc)

    return func.now()


def _record_income_event(
    db_session: Session,
    event_type: str,
    income_model: IncomeModel,
    account_id: Optional[UUID],
    ingestion_mode: str,
) -> FinancialEventModel:
    today = server_today()

    return financial_event_repository.create_event(
        db_session=db_session,
        user_id=income_model.user_id,
        event_type=event_type,
        aggregate_type=AGGREGATE_TYPE_INCOME,
        aggregate_id=income_model.id,
        origin=ORIGIN_MANUAL,
        ingestion_mode=ingestion_mode,
        snap_amount=income_model.amount,
        snap_currency=income_model.currency,
        snap_received_at=income_model.received_at,
        snap_account_id=account_id,
        snap_income_source=income_model.source,
        snap_aggregate_updated_at=income_model.updated_at,
        not_before=compute_not_before(income_model.received_at, today),
    )


# Records the income.created event for a just-created manual Income.
# It runs INSIDE the caller's transaction (the Income and, when linked, its
# AccountTransaction projection are already flushed) and never commits.
# The snapshot is read from the persisted Income row (amount, never
# base_amount; the persisted updated_at).
# Parameters:
# - db_session: the caller's session.
# - income_model: the flushed and refreshed Income.
# - account_id: the linked Account id, or None.
# Returns:
# - The flushed event.
def record_income_created(
    db_session: Session,
    income_model: IncomeModel,
    account_id: Optional[UUID],
) -> FinancialEventModel:
    return _record_income_event(
        db_session=db_session,
        event_type=EVENT_INCOME_CREATED,
        income_model=income_model,
        account_id=account_id,
        ingestion_mode=classify_manual_creation(
            income_model.received_at, server_today(),
        ),
    )


# Records the income.updated event (manual/correction) with the FINAL
# snapshot after the accepted update, including the final Account link.
# Never commits.
# Parameters:
# - db_session: the caller's session.
# - income_model: the updated, flushed and refreshed Income.
# - account_id: the final linked Account id, or None.
# Returns:
# - The flushed event.
def record_income_updated(
    db_session: Session,
    income_model: IncomeModel,
    account_id: Optional[UUID],
) -> FinancialEventModel:
    return _record_income_event(
        db_session=db_session,
        event_type=EVENT_INCOME_UPDATED,
        income_model=income_model,
        account_id=account_id,
        ingestion_mode=INGESTION_CORRECTION,
    )


# Records the income.deleted event (manual/correction) with the last
# canonical state captured immediately before the Income row is deleted.
# Never commits. The event survives the deletion because aggregate_id is a
# soft reference.
# Parameters:
# - db_session: the caller's session.
# - income_model: the still-present, locked Income.
# - account_id: the Account linked immediately before deletion, or None.
# Returns:
# - The flushed event.
def record_income_deleted(
    db_session: Session,
    income_model: IncomeModel,
    account_id: Optional[UUID],
) -> FinancialEventModel:
    return _record_income_event(
        db_session=db_session,
        event_type=EVENT_INCOME_DELETED,
        income_model=income_model,
        account_id=account_id,
        ingestion_mode=INGESTION_CORRECTION,
    )
