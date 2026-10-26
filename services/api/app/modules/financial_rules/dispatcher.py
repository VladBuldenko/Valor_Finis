"""
Periodic financial rules and alerts dispatcher (VF-020E10, APPROVED P50 / P87).

What:
    A separate, finite process that runs ONE bounded pass and exits:
    `python -m app.modules.financial_rules.dispatcher` (cwd = services/api). It is
    meant for a scheduler such as a Render Cron Job (about every 10 minutes) and
    never runs inside the FastAPI web process.

    Pass:
        1. Event drain: discover (cross-user, from financial_events only) the
           users whose strict-FIFO head can make progress and drain each one with
           the existing per-user drain (claim / lease / retry / dead, AUTO and
           CONFIRM, lazy proposal expiry - all reused unchanged).
        2. Alert evaluation: for a per-run random sample of the users that have an
           enabled alert rule, run the existing E9B evaluation, independent of any
           Income event.

Why:
    Without a durable scheduler AUTO executes only at the next user-triggered
    drain. All financial correctness stays in the reused services (per-user lock
    L0, event claim tokens, execution uniqueness, alert unique constraints), so
    overlapping dispatchers, a user-triggered evaluate or a crash cannot create a
    duplicate effect: this module only decides WHICH users to serve and reports.

Exit codes:
    0  success / no-op / disabled
    1  fatal infrastructure failure (database unreachable)
    2  invalid configuration (nothing was started)
    3  completed, but with failures (user failure, retryable or dead events,
       alert failure) - the run is visible as failed to the scheduler

Logs carry counters and short user hashes only: never the database URL, secrets,
amounts or names.
"""

import hashlib
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping, Optional
from uuid import UUID

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal, engine
from app.modules.financial_events import financial_event_processor
from app.modules.financial_events import financial_event_queue_repository as queue
from app.modules.financial_rules import rule_alert_repository, rule_alert_service

logger = logging.getLogger("valor.dispatcher")

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_CONFIG = 2
EXIT_COMPLETED_WITH_FAILURES = 3

OUTCOME_SUCCESS = "success"
OUTCOME_NOOP = "noop"
OUTCOME_DISABLED = "disabled"
OUTCOME_FAILURES = "completed_with_failures"
OUTCOME_FATAL = "fatal"

# Three consecutive connection-level failures mean the database is gone: stop
# instead of hammering it for every remaining user.
MAX_CONSECUTIVE_CONNECTION_ERRORS = 3
# Three consecutive users failing the same phase is systemic, not per-user.
MAX_CONSECUTIVE_FAILURES = MAX_CONSECUTIVE_CONNECTION_ERRORS

# Bounded defaults (derived from the contract, not an SLA): at most 50 users x 20
# events per pass (the per-user cap equals the evaluate endpoint default), up to
# 200 alert users, and a 240 s work budget so a pass ends well before the next
# 10-minute tick.
DEFAULT_MAX_USERS = 50
DEFAULT_MAX_EVENTS_PER_USER = 20
DEFAULT_MAX_ALERT_USERS = 200
DEFAULT_TIME_BUDGET_SECONDS = 240


class DispatcherConfigError(Exception):
    """Raised before any work starts when an environment value is invalid."""


@dataclass(frozen=True)
class DispatcherConfig:
    enabled: bool = True
    max_users: int = DEFAULT_MAX_USERS
    max_events_per_user: int = DEFAULT_MAX_EVENTS_PER_USER
    max_alert_users: int = DEFAULT_MAX_ALERT_USERS
    time_budget_seconds: int = DEFAULT_TIME_BUDGET_SECONDS


def _bounded_int(environ: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = environ.get(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = int(raw.strip())
    except ValueError:
        raise DispatcherConfigError(f"{name} must be an integer.") from None

    if not low <= value <= high:
        raise DispatcherConfigError(f"{name} must be between {low} and {high}.")

    return value


def load_config(environ: Optional[Mapping[str, str]] = None) -> DispatcherConfig:
    environment = os.environ if environ is None else environ
    raw_enabled = environment.get("RULE_DISPATCHER_ENABLED", "true").strip().lower()

    if raw_enabled not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise DispatcherConfigError("RULE_DISPATCHER_ENABLED must be true or false.")

    return DispatcherConfig(
        enabled=raw_enabled in ("true", "1", "yes", "on"),
        max_users=_bounded_int(environment, "RULE_DISPATCHER_MAX_USERS", DEFAULT_MAX_USERS, 1, 1000),
        max_events_per_user=_bounded_int(
            environment, "RULE_DISPATCHER_MAX_EVENTS_PER_USER", DEFAULT_MAX_EVENTS_PER_USER, 1,
            financial_event_processor.MAX_DRAIN_LIMIT,
        ),
        max_alert_users=_bounded_int(
            environment, "RULE_DISPATCHER_MAX_ALERT_USERS", DEFAULT_MAX_ALERT_USERS, 1, 5000,
        ),
        time_budget_seconds=_bounded_int(
            environment, "RULE_DISPATCHER_TIME_BUDGET_SECONDS", DEFAULT_TIME_BUDGET_SECONDS, 5, 3300,
        ),
    )


@dataclass
class DispatcherSummary:
    """Non-sensitive counters of one pass."""

    outcome: str = OUTCOME_NOOP
    users_considered: int = 0
    users_processed: int = 0
    events_processed: int = 0
    events_deferred: int = 0
    events_failed_retryable: int = 0
    events_dead: int = 0
    events_unrecorded_failures: int = 0
    users_blocked: int = 0
    user_failures: int = 0
    alert_users_total: int = 0
    alert_users_considered: int = 0
    alert_users_evaluated: int = 0
    alerts_created: int = 0
    alerts_resolved: int = 0
    alert_failures: int = 0
    alerts_unavailable: bool = False
    alert_users_truncated: bool = False
    budget_exhausted: bool = False
    execution_outcomes: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    @property
    def failure_count(self) -> int:
        return (
            self.user_failures + self.alert_failures + self.events_failed_retryable
            + self.events_dead + self.events_unrecorded_failures
        )


class _FatalError(Exception):
    """An infrastructure failure that stops the whole pass."""


def _user_tag(user_id: UUID) -> str:
    # A short hash correlates log lines without exposing the user identifier.
    return hashlib.sha256(user_id.bytes).hexdigest()[:8]


def _is_connection_error(error: Exception) -> bool:
    return isinstance(error, (OperationalError, InterfaceError))


def _drain_event_users(
    config: DispatcherConfig,
    summary: DispatcherSummary,
    session_factory: Callable[[], Session],
    out_of_time: Callable[[], bool],
) -> None:
    try:
        with session_factory() as session:
            users = queue.discover_users_with_progressing_head(session, config.max_users)
    except Exception as error:
        raise _FatalError(f"event discovery failed ({type(error).__name__})") from error

    summary.users_considered = len(users)
    consecutive_connection_errors = 0

    for user_id in users:
        if out_of_time():
            summary.budget_exhausted = True
            return

        try:
            with session_factory() as session:
                drained = financial_event_processor.drain_user_events(
                    session, user_id, config.max_events_per_user,
                )
        except Exception as error:
            summary.user_failures += 1
            logger.error("event drain failed for user %s (%s)", _user_tag(user_id), type(error).__name__)

            if _is_connection_error(error):
                consecutive_connection_errors += 1

                if consecutive_connection_errors >= MAX_CONSECUTIVE_CONNECTION_ERRORS:
                    raise _FatalError("database connection lost") from error
            continue

        summary.events_unrecorded_failures += drained.unrecorded_failures

        if drained.unrecorded_failures:
            # The failure could not even be recorded: count it like a connection
            # error so a database outage cannot look like a quiet success.
            consecutive_connection_errors += 1

            if consecutive_connection_errors >= MAX_CONSECUTIVE_CONNECTION_ERRORS:
                raise _FatalError("database connection lost")
        else:
            consecutive_connection_errors = 0

        summary.users_processed += 1
        summary.events_processed += drained.processed
        summary.events_deferred += drained.deferred
        summary.events_failed_retryable += drained.failed_retryable
        summary.events_dead += drained.dead
        summary.users_blocked += 1 if drained.blocked else 0

        for status, count in drained.outcomes.items():
            summary.execution_outcomes[status] = summary.execution_outcomes.get(status, 0) + count


def _evaluate_alert_users(
    config: DispatcherConfig,
    summary: DispatcherSummary,
    session_factory: Callable[[], Session],
    out_of_time: Callable[[], bool],
    seed: str,
) -> None:
    try:
        with session_factory() as session:
            if not rule_alert_repository.table_exists(session):
                # Missing storage is a known staged state, NOT a failure.
                summary.alerts_unavailable = True
                logger.warning("rule_alerts table is not available; alert evaluation skipped")
                return

            summary.alert_users_total = rule_alert_repository.count_users_with_enabled_alert_rules(session)
            users = rule_alert_repository.get_users_with_enabled_alert_rules_sample(
                session, config.max_alert_users, seed,
            )
    except Exception as error:
        summary.alert_failures += 1
        logger.error("alert discovery failed (%s)", type(error).__name__)

        if _is_connection_error(error):
            raise _FatalError("database connection lost") from error
        return

    summary.alert_users_considered = len(users)
    # More enabled-alert users than one pass may evaluate: coverage is now
    # probabilistic across runs. Operators should watch this flag.
    summary.alert_users_truncated = summary.alert_users_total > len(users)
    consecutive_failures = 0

    for user_id in users:
        if out_of_time():
            summary.budget_exhausted = True
            return

        try:
            with session_factory() as session:
                result = rule_alert_service.evaluate_user_alerts_best_effort(session, user_id)
        except Exception as error:  # the best-effort wrapper never raises; opening the session may
            summary.alert_failures += 1
            consecutive_failures += 1
            logger.error("alert evaluation failed for user %s (%s)", _user_tag(user_id), type(error).__name__)

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise _FatalError("alert evaluation failed for consecutive users") from error
            continue

        if result.failed:
            summary.alert_failures += 1
            consecutive_failures += 1
            logger.error("alert evaluation failed for user %s", _user_tag(user_id))

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise _FatalError("alert evaluation failed for consecutive users")
            continue

        consecutive_failures = 0

        if not result.available:
            summary.alerts_unavailable = True
        else:
            summary.alert_users_evaluated += 1
            summary.alerts_created += result.created
            summary.alerts_resolved += result.resolved


# Runs one bounded pass and returns its counters. The two phases are isolated:
# a fatal infrastructure failure in the drain stops the pass (nothing else could
# work), while an alert problem never prevents the already finished drain from
# being reported.
def run_once(
    config: DispatcherConfig,
    session_factory: Callable[[], Session] = SessionLocal,
    monotonic: Callable[[], float] = time.monotonic,
    seed: Optional[str] = None,
) -> DispatcherSummary:
    summary = DispatcherSummary()
    started = monotonic()

    if not config.enabled:
        summary.outcome = OUTCOME_DISABLED
        return summary

    # The last fifth of the budget is reserved for the alert phase, so a large
    # event backlog can never starve alert evaluation on every run.
    alert_reserve = max(1, config.time_budget_seconds // 5)

    def drain_out_of_time() -> bool:
        return monotonic() - started >= config.time_budget_seconds - alert_reserve

    def out_of_time() -> bool:
        return monotonic() - started >= config.time_budget_seconds

    # A fresh seed per run (never derived from the clock) reshuffles the alert users.
    run_seed = uuid.uuid4().hex if seed is None else seed

    try:
        _drain_event_users(config, summary, session_factory, drain_out_of_time)
        _evaluate_alert_users(config, summary, session_factory, out_of_time, run_seed)
    except _FatalError as error:
        logger.error("fatal: %s", error)
        summary.outcome = OUTCOME_FATAL
        summary.elapsed_seconds = round(monotonic() - started, 3)
        return summary

    summary.elapsed_seconds = round(monotonic() - started, 3)

    if summary.failure_count:
        summary.outcome = OUTCOME_FAILURES
    elif summary.users_considered == 0 and summary.alert_users_considered == 0:
        summary.outcome = OUTCOME_NOOP
    else:
        summary.outcome = OUTCOME_SUCCESS

    return summary


def exit_code_for(summary: DispatcherSummary) -> int:
    if summary.outcome == OUTCOME_FATAL:
        return EXIT_FATAL

    if summary.outcome == OUTCOME_FAILURES:
        return EXIT_COMPLETED_WITH_FAILURES

    return EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        stream=sys.stdout, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        config = load_config()
    except DispatcherConfigError as error:
        logger.error("invalid dispatcher configuration: %s", error)
        return EXIT_CONFIG

    try:
        summary = run_once(config)
    finally:
        # Release every pooled connection so the process exits promptly.
        engine.dispose()

    level = logging.ERROR if summary.outcome in (OUTCOME_FATAL, OUTCOME_FAILURES) else logging.INFO
    logger.log(level, "dispatcher_summary %s", json.dumps(asdict(summary), sort_keys=True))

    return exit_code_for(summary)


if __name__ == "__main__":
    raise SystemExit(main())
