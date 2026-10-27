from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# Persistent alert-dispatch progress (VF-020E10, migration c4d8a2f6e193). Only the
# periodic dispatcher uses these functions. The table and sequence are private
# (no Data API privilege) and hold scheduling state only.

ENABLED_ALERT_RULES_SQL = (
    "status = 'enabled' AND rule_type IN "
    "('MINIMUM_UNALLOCATED_FLOOR', 'OVERCOMMITMENT_ALERT', 'BUDGET_ALERT')"
)
ERROR_CODE_MAX_LENGTH = 64


# Whether the progress table exists. A genuine database error PROPAGATES (it is
# never read as "absent"): only a successful query returning false means the
# schema stage has not been applied.
def table_exists(db_session: Session) -> bool:
    return bool(
        db_session.execute(text("SELECT to_regclass('public.alert_dispatch_progress') IS NOT NULL")).scalar_one()
    )


# The next users to serve, in a strict total order that never depends on a clock:
#   1. users with NO progress row (never attempted, including newly enabled ones),
#      by user_id;
#   2. then users by ascending service_seq, i.e. least recently ATTEMPTED first
#      (a sequence value is drawn on every attempt, success or failure, and is
#      UNIQUE, so there are no ties).
# Only users with at least one ENABLED alert rule are candidates, so the old row
# of a disabled or deleted user can never cause processing.
def select_next_users(db_session: Session, limit: int) -> list[UUID]:
    rows = db_session.execute(
        text(
            "SELECT u.user_id FROM ("
            f"SELECT DISTINCT user_id FROM financial_rules WHERE {ENABLED_ALERT_RULES_SQL}"
            ") AS u LEFT JOIN alert_dispatch_progress AS p ON p.user_id = u.user_id "
            "ORDER BY p.service_seq ASC NULLS FIRST, u.user_id ASC LIMIT :limit"
        ),
        {"limit": limit},
    ).all()

    return [row[0] for row in rows]


# Draws the ATTEMPT identity of one evaluation. It must be called by the evaluation
# transaction right AFTER it acquired the per-user lock L0: a competing attempt for
# the same user can only draw after this transaction ended, so for one user the
# attempt order equals the L0 acquisition order and the values are strictly
# increasing. nextval() is never rolled back, so the value stays valid (the caller
# keeps it in memory) even when the evaluation fails and rolls back; a rolled back
# attempt merely leaves a gap, which the ordering does not mind. No clock is used.
def allocate_attempt_seq(db_session: Session) -> int:
    return int(db_session.execute(text("SELECT nextval('alert_dispatch_service_seq')")).scalar_one())


# Both writers below are STALE-WRITE GUARDED: the row is only replaced while its
# service_seq is OLDER than the writer's attempt identity, so an older attempt that
# reports late (for example a failure recorded after a newer attempt already
# succeeded) changes nothing. The guard is evaluated against the committed row
# under the row lock (READ COMMITTED re-checks the WHERE after waiting for a
# concurrent writer), so concurrent writers cannot both win.
#
# Timestamps never rely on the clock moving forward: now() is the transaction START
# time and wall clocks can step back. last_attempted_at therefore only ever grows
# (GREATEST of the stored value and now()), which keeps the table CHECK
# last_success_at <= last_attempted_at valid without a schema change.


# Records a SUCCESSFUL evaluation. It must run inside the SAME transaction that
# commits the alert evaluation, so success is never recorded before (or without)
# the alert transaction committing: both commit together or neither does. Returns
# False when a newer attempt is already recorded (the write was ignored).
def record_success(db_session: Session, user_id: UUID, attempt_seq: int) -> bool:
    result = db_session.execute(
        text(
            "INSERT INTO alert_dispatch_progress "
            "(user_id, service_seq, last_attempted_at, last_success_at, consecutive_failures, last_error_code) "
            "VALUES (:user_id, :seq, now(), now(), 0, NULL) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "service_seq = EXCLUDED.service_seq, "
            "last_attempted_at = GREATEST(alert_dispatch_progress.last_attempted_at, EXCLUDED.last_attempted_at), "
            "last_success_at = GREATEST(alert_dispatch_progress.last_attempted_at, EXCLUDED.last_attempted_at), "
            "consecutive_failures = 0, last_error_code = NULL "
            "WHERE alert_dispatch_progress.service_seq < EXCLUDED.service_seq"
        ),
        {"user_id": user_id, "seq": attempt_seq},
    )

    return bool(result.rowcount)


# Records a FAILED attempt in its own short transaction (the failed evaluation
# was rolled back and its lock released). The user still moves to the back of the
# order, so a user that keeps failing is retried once per cycle and cannot
# monopolize the queue; its failure counter and error CODE (an exception class
# name, never a message) stay visible for monitoring. last_success_at is left
# unchanged. Returns False when a newer attempt is already recorded: the stale
# failure is ignored (the dispatcher still counts it in its run summary).
def record_failure(db_session: Session, user_id: UUID, attempt_seq: int, error_code: Optional[str]) -> bool:
    result = db_session.execute(
        text(
            "INSERT INTO alert_dispatch_progress "
            "(user_id, service_seq, last_attempted_at, last_success_at, consecutive_failures, last_error_code) "
            "VALUES (:user_id, :seq, now(), NULL, 1, :code) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "service_seq = EXCLUDED.service_seq, "
            "last_attempted_at = GREATEST(alert_dispatch_progress.last_attempted_at, "
            "alert_dispatch_progress.last_success_at, EXCLUDED.last_attempted_at), "
            "consecutive_failures = alert_dispatch_progress.consecutive_failures + 1, "
            "last_error_code = EXCLUDED.last_error_code "
            "WHERE alert_dispatch_progress.service_seq < EXCLUDED.service_seq"
        ),
        {"user_id": user_id, "seq": attempt_seq, "code": (error_code or "unknown")[:ERROR_CODE_MAX_LENGTH]},
    )

    return bool(result.rowcount)


# Bounded housekeeping: deletes the progress rows of users that no longer have an
# enabled alert rule. A user that is enabled again simply has no row and is served
# first. Returns the number of rows deleted.
def purge_stale(db_session: Session, limit: int) -> int:
    result = db_session.execute(
        text(
            "DELETE FROM alert_dispatch_progress WHERE user_id IN ("
            "SELECT p.user_id FROM alert_dispatch_progress AS p WHERE NOT EXISTS ("
            "SELECT 1 FROM financial_rules AS r WHERE r.user_id = p.user_id "
            "AND r.status = 'enabled' AND r.rule_type IN "
            "('MINIMUM_UNALLOCATED_FLOOR', 'OVERCOMMITMENT_ALERT', 'BUDGET_ALERT')"
            ") ORDER BY p.user_id LIMIT :limit)"
        ),
        {"limit": limit},
    )

    return int(result.rowcount or 0)
