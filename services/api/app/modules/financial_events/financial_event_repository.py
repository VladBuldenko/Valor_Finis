import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.financial_events.financial_event_models import FinancialEventModel


# Inserts one financial_events row inside the caller's transaction.
# This function exists as the single narrow write primitive of the outbox
# (VF-020E3). TRANSACTION OWNERSHIP BELONGS TO THE CALLER: it only adds and
# flushes (and refreshes to load the server defaults) and NEVER commits or
# rolls back, so the event is atomic with the canonical mutation that the
# composing service commits - or rolls back - as one unit. It deliberately
# has no commit parameter, so an independent commit is structurally
# impossible. occurred_at, status and attempts are left to the E2 server
# defaults (now(), pending, 0).
# Parameters:
# - db_session: active SQLAlchemy database session owned by the caller.
# - user_id: owner of the event.
# - event_type / aggregate_type / aggregate_id: event identity and the soft
#   source reference.
# - origin / ingestion_mode: provenance.
# - snap_*: the typed source snapshot.
# - not_before: business-date deferral timestamp, or a SQL expression such
#   as func.now() evaluated by the database.
# Returns:
# - The flushed FinancialEventModel with its server defaults loaded.
def create_event(
    db_session: Session,
    user_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    origin: str,
    ingestion_mode: str,
    snap_amount: Decimal,
    snap_currency: str,
    snap_received_at: date,
    snap_account_id: Optional[UUID],
    snap_income_source: str,
    snap_aggregate_updated_at: datetime,
    not_before: Union[datetime, ColumnElement],
) -> FinancialEventModel:
    event_model = FinancialEventModel(
        id=uuid.uuid4(),
        user_id=user_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        origin=origin,
        ingestion_mode=ingestion_mode,
        snap_amount=snap_amount,
        snap_currency=snap_currency,
        snap_received_at=snap_received_at,
        snap_account_id=snap_account_id,
        snap_income_source=snap_income_source,
        snap_aggregate_updated_at=snap_aggregate_updated_at,
        not_before=not_before,
    )

    db_session.add(event_model)
    db_session.flush()
    db_session.refresh(event_model)

    return event_model
