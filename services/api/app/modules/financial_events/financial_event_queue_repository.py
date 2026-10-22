from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, update
from sqlalchemy.orm import Session

from app.modules.financial_events.financial_event_models import FinancialEventModel

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED_RETRYABLE = "failed_retryable"
STATUS_DEAD = "dead"

UNFINISHED_STATUSES = (STATUS_PENDING, STATUS_PROCESSING, STATUS_FAILED_RETRYABLE)

# VF-020E1 contract constants (APPROVED P82). No jitter in v1.
LEASE_DURATION = timedelta(minutes=5)
MAX_ATTEMPTS = 6
# Delay after failed attempt N (1-based); the sixth failed attempt is dead.
RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)

ERROR_LEASE_EXPIRED_MAX_ATTEMPTS = "lease_expired_max_attempts"


# Returns the user's FIFO head: the first unfinished event, in
# (occurred_at, id) order, that is not business-date deferred. Head selection
# deliberately happens over ALL such events BEFORE any claimability decision
# (APPROVED P52): filtering to "claimable" rows first would let a newer event
# bypass an older one that is leased or waiting for its retry. The row is
# locked so two claimers can never decide on the same head concurrently.
# Parameters:
# - db_session: active session (the caller holds the user's L0 lock).
# - user_id: owner whose queue is read.
# Returns:
# - The locked head event, or None when the user has no due unfinished event.
def select_head_for_update(
    db_session: Session, user_id: UUID,
) -> Optional[FinancialEventModel]:
    return (
        db_session.query(FinancialEventModel)
        .filter(
            FinancialEventModel.user_id == user_id,
            FinancialEventModel.status.in_(UNFINISHED_STATUSES),
            or_(
                FinancialEventModel.not_before.is_(None),
                FinancialEventModel.not_before <= func.now(),
            ),
        )
        .order_by(FinancialEventModel.occurred_at.asc(), FinancialEventModel.id.asc())
        .limit(1)
        .with_for_update()
        .first()
    )


# Whether the head may be claimed now (P52 step 2). Evaluated against the
# database clock through a scalar so the decision shares one time source with
# head selection.
def is_claimable(db_session: Session, event_model: FinancialEventModel) -> bool:
    if event_model.status == STATUS_PENDING:
        return True

    if event_model.status == STATUS_FAILED_RETRYABLE:
        return _database_clock_reached(
            db_session, event_model.id, FinancialEventModel.next_attempt_at,
        )

    if event_model.status == STATUS_PROCESSING:
        return _database_clock_reached(
            db_session, event_model.id, FinancialEventModel.lease_expires_at,
        )

    return False


def _database_clock_reached(db_session: Session, event_id: UUID, column: Any) -> bool:
    return bool(
        db_session.query(column <= func.now())
        .filter(FinancialEventModel.id == event_id)
        .scalar()
    )


def mark_dead_lease_expired(db_session: Session, event_model: FinancialEventModel) -> None:
    event_model.status = STATUS_DEAD
    event_model.last_error_code = ERROR_LEASE_EXPIRED_MAX_ATTEMPTS
    event_model.lease_expires_at = None
    event_model.next_attempt_at = None
    event_model.claim_token = None
    db_session.flush()


def claim(
    db_session: Session, event_model: FinancialEventModel, claim_token: UUID,
) -> None:
    event_model.status = STATUS_PROCESSING
    event_model.attempts = event_model.attempts + 1
    event_model.claim_token = claim_token
    event_model.lease_expires_at = func.now() + LEASE_DURATION
    event_model.next_attempt_at = None
    db_session.flush()
    db_session.refresh(event_model)


# Returns a claimed event to the queue without a delivery outcome (it turned
# out not to be the head after all, or it is business-date deferred). The
# attempt that the claim counted is given back.
def release_claim(
    db_session: Session,
    event_model: FinancialEventModel,
    not_before: Optional[datetime] = None,
) -> None:
    event_model.status = STATUS_PENDING
    event_model.attempts = max(event_model.attempts - 1, 0)
    event_model.claim_token = None
    event_model.lease_expires_at = None
    event_model.next_attempt_at = None

    if not_before is not None:
        event_model.not_before = not_before

    db_session.flush()


def mark_processed(
    db_session: Session, event_model: FinancialEventModel, outcome_summary: dict[str, Any],
) -> None:
    event_model.status = STATUS_PROCESSED
    event_model.processed_at = func.now()
    event_model.outcome_summary = outcome_summary
    event_model.claim_token = None
    event_model.lease_expires_at = None
    event_model.next_attempt_at = None
    event_model.last_error_code = None
    db_session.flush()


# Records a technical failure of the claim identified by claim_token, in its
# own short transaction. The UPDATE is conditional on the claim still being
# ours, so a lease that expired and was reclaimed by another worker is never
# overwritten. attempts is read from the row (the claim already counted it):
# attempts < 6 -> failed_retryable with the contract delay; the sixth failed
# attempt -> dead.
# Returns:
# - The resulting status, or None when the claim is no longer ours.
def record_technical_failure(
    db_session: Session, event_id: UUID, claim_token: UUID, error_code: str,
) -> Optional[str]:
    attempts = (
        db_session.query(FinancialEventModel.attempts)
        .filter(
            FinancialEventModel.id == event_id,
            FinancialEventModel.claim_token == claim_token,
            FinancialEventModel.status == STATUS_PROCESSING,
        )
        .with_for_update()
        .scalar()
    )

    if attempts is None:
        return None

    if attempts >= MAX_ATTEMPTS:
        values: dict[str, Any] = {
            "status": STATUS_DEAD,
            "next_attempt_at": None,
        }
        resulting_status = STATUS_DEAD
    else:
        values = {
            "status": STATUS_FAILED_RETRYABLE,
            "next_attempt_at": func.now() + RETRY_DELAYS[attempts - 1],
        }
        resulting_status = STATUS_FAILED_RETRYABLE

    db_session.execute(
        update(FinancialEventModel)
        .where(
            and_(
                FinancialEventModel.id == event_id,
                FinancialEventModel.claim_token == claim_token,
            )
        )
        .values(
            last_error_code=error_code,
            lease_expires_at=None,
            claim_token=None,
            **values,
        )
    )

    return resulting_status
