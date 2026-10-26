import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.app_config import settings
from app.db.database_session import SessionLocal
from app.modules.financial_events import financial_event_queue_repository as queue
from app.modules.financial_events.financial_event_models import FinancialEventModel
from app.modules.financial_rules import rule_alert_service, rule_execution_service
from app.modules.goals import goal_user_lock

logger = logging.getLogger(__name__)

DEFAULT_DRAIN_LIMIT = 20
MAX_DRAIN_LIMIT = 100

ERROR_DEADLOCK = "deadlock_detected"
ERROR_SERIALIZATION = "serialization_failure"
ERROR_PROCESSING = "processing_error"

PG_DEADLOCK = "40P01"
PG_SERIALIZATION = "40001"


@dataclass
class DrainSummary:
    """Counters returned by one bounded drain of a single user's queue."""

    processed: int = 0
    deferred: int = 0
    failed_retryable: int = 0
    dead: int = 0
    blocked: bool = False
    outcomes: dict[str, int] = field(default_factory=dict)


@dataclass
class _Claim:
    event_id: UUID
    claim_token: UUID


def _error_code(error: Exception) -> str:
    pgcode = getattr(getattr(error, "orig", None), "pgcode", None)

    if isinstance(error, DBAPIError) and pgcode == PG_DEADLOCK:
        return ERROR_DEADLOCK

    if isinstance(error, DBAPIError) and pgcode == PG_SERIALIZATION:
        return ERROR_SERIALIZATION

    return ERROR_PROCESSING


# Claims the user's next claimable head in one short, durable transaction
# (§12.4 step 1). The head is selected over ALL unfinished, non-deferred events
# first and only then tested for claimability, so a newer event can never
# bypass an older one that is leased or waiting for its retry (APPROVED P52).
# An abandoned max-attempt lease (or any head that already used every attempt)
# becomes dead instead of getting a seventh attempt, and the loop then selects
# the next head, because dead never blocks.
# Returns:
# - The claim, or None when nothing is due or the head blocks the queue.
def _claim_next(db_session: Session, user_id: UUID) -> tuple[Optional[_Claim], bool]:
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        while True:
            head = queue.select_head_for_update(db_session, user_id)

            if head is None:
                db_session.commit()
                return None, False

            if not queue.is_claimable(db_session, head):
                db_session.commit()
                return None, True

            if head.attempts >= queue.MAX_ATTEMPTS:
                queue.mark_dead_lease_expired(db_session, head)
                db_session.commit()
                goal_user_lock.acquire_goal_user_lock(db_session, user_id)
                continue

            claim_token = uuid.uuid4()
            queue.claim(db_session, head, claim_token)
            claim = _Claim(event_id=head.id, claim_token=claim_token)
            db_session.commit()

            return claim, False
    except Exception:
        db_session.rollback()
        raise


def _record_failure(
    db_session: Session, claim: _Claim, error: Exception, summary: DrainSummary,
) -> None:
    code = _error_code(error)

    try:
        status = queue.record_technical_failure(
            db_session, claim.event_id, claim.claim_token, code,
        )
        db_session.commit()
    except Exception:
        # The lease simply expires and the event is recovered by the reclaim
        # path; nothing financial was committed.
        db_session.rollback()
        logger.error("could not record the failure of event %s", claim.event_id)
        return

    if status == queue.STATUS_DEAD:
        summary.dead += 1
    elif status == queue.STATUS_FAILED_RETRYABLE:
        summary.failed_retryable += 1

    # Identifiers and codes only: exception text can carry SQL parameters.
    logger.warning(
        "financial event %s failed technically: %s (%s)",
        claim.event_id, code, type(error).__name__,
    )


# Processes one claimed event in a single atomic transaction (§12.4 step 2):
# L0 -> event FOR UPDATE -> claim and FIFO verification -> rules -> writes ->
# processed -> commit. Any exception rolls EVERYTHING back (including partial
# execution rows) and is recorded as a technical failure in a separate short
# transaction; business outcomes are committed results and never retried.
# Returns:
# - "processed", "deferred", "not_head" or "failed".
def _process_claimed(
    db_session: Session, user_id: UUID, claim: _Claim, summary: DrainSummary,
) -> str:
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        event_model = (
            db_session.query(FinancialEventModel)
            .filter(
                FinancialEventModel.id == claim.event_id,
                FinancialEventModel.user_id == user_id,
            )
            .with_for_update()
            .first()
        )

        if (
            event_model is None
            or event_model.status != queue.STATUS_PROCESSING
            or event_model.claim_token != claim.claim_token
        ):
            # The lease expired and the event was reclaimed or finished by
            # another worker: nothing to do, nothing to overwrite.
            db_session.rollback()
            return "not_head"

        head = queue.select_head_for_update(db_session, user_id)

        if head is None or head.id != event_model.id:
            # An older event became visible after the claim: give the attempt
            # back and let the next claim pick the true head.
            queue.release_claim(db_session, event_model)
            db_session.commit()
            return "not_head"

        try:
            outcome = rule_execution_service.process_event(db_session, user_id, event_model)
        except rule_execution_service.EventDeferredError as deferral:
            # Raised before any financial write: only the claim is returned.
            queue.release_claim(db_session, event_model, not_before=deferral.not_before)
            db_session.commit()
            summary.deferred += 1
            return "deferred"

        queue.mark_processed(db_session, event_model, outcome)
        db_session.commit()
    except Exception as error:
        db_session.rollback()
        _record_failure(db_session, claim, error, summary)
        return "failed"

    summary.processed += 1

    for status, count in outcome["executions"].items():
        summary.outcomes[status] = summary.outcomes.get(status, 0) + count

    return "processed"


# Drains at most `limit` due events of ONE user in strict FIFO order. The loop
# stops as soon as the head blocks (live lease, waiting retry, nothing due) or
# an attempt fails, because a failed head blocks the user's newer events by
# design (head-of-line). It never scans Income and never touches other users.
# Parameters:
# - db_session: a fresh session with no open transaction.
# - user_id: the authenticated owner whose queue is drained.
# - limit: bounded number of events for this call.
def drain_user_events(
    db_session: Session, user_id: UUID, limit: int = DEFAULT_DRAIN_LIMIT,
) -> DrainSummary:
    summary = DrainSummary()
    bounded = max(1, min(limit, MAX_DRAIN_LIMIT))
    handled = 0

    while handled < bounded:
        claim, blocked = _claim_next(db_session, user_id)

        if claim is None:
            summary.blocked = blocked
            break

        handled += 1
        result = _process_claimed(db_session, user_id, claim, summary)

        if result == "failed":
            break

    return summary


# Best-effort, post-response drain used as a FastAPI background task after an
# Income write. It opens its own session, swallows and logs every failure and
# never touches the response that was already sent: the events are durable in
# the outbox, so a lost task only delays execution to the next drain.
def dispatch_user_events_best_effort(user_id: UUID) -> None:
    if not settings.rule_event_background_dispatch:
        return

    db_session = SessionLocal()

    try:
        drain_user_events(db_session, user_id)
        # Detect alert transitions caused by the drain (never raises).
        rule_alert_service.evaluate_user_alerts_best_effort(db_session, user_id)
    except Exception as error:
        logger.error("best-effort event dispatch failed (%s)", type(error).__name__)
    finally:
        db_session.close()
