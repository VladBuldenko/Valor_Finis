import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts import account_service
from app.modules.analytics import analytics_service
from app.modules.budgets.budget_period import PERIOD_ACTIVE
from app.modules.financial_events import financial_event_service
from app.modules.financial_rules import rule_alert_repository
from app.modules.financial_rules.financial_rule_errors import RuleAlertNotFoundError
from app.modules.financial_rules.financial_rule_models import FinancialRuleModel
from app.modules.financial_rules.rule_alert_schemas import (
    RuleAlertListResponse,
    RuleAlertResponse,
)
from app.modules.goals import goal_user_lock

logger = logging.getLogger(__name__)

RULE_FLOOR = "MINIMUM_UNALLOCATED_FLOOR"
RULE_OVERCOMMITMENT = "OVERCOMMITMENT_ALERT"
RULE_BUDGET = "BUDGET_ALERT"

LEVEL_BREACHED = "breached"
# Budget severity order: an alert is created only for an UPWARD transition.
BUDGET_LEVEL_RANK = {"watch": 1, "at_risk": 2, "exceeded": 3}

ZERO = Decimal("0.00")


@dataclass
class AlertEvaluation:
    """Counters of one alert evaluation; available is False without the schema."""

    available: bool = True
    created: int = 0
    resolved: int = 0
    # True when the evaluation raised (a genuine database or code failure). It is
    # deliberately separate from `available`, which only means "the E9A table is
    # not there": a failure must never be reported as a missing schema.
    failed: bool = False
    # The exception class name when `failed` (a code, never a message).
    error_code: Optional[str] = None


# Account episode lifecycle for one rule (floor breach or overcommitment).
# breached + open episode: nothing (the episode continues);
# breached + no open episode: a NEW episode E<n+1> (a later breach after
#   recovery is a new row);
# not breached + open episode: the episode is resolved (the Account recovered).
def _apply_account_episode(
    db_session: Session,
    user_id: UUID,
    rule_model: FinancialRuleModel,
    breached: bool,
    result: AlertEvaluation,
) -> None:
    open_episode = rule_alert_repository.get_open_episode(
        db_session, user_id, rule_model.rule_type, rule_model.source_account_id,
    )

    if breached and open_episode is None:
        number = rule_alert_repository.get_last_episode_number(
            db_session, user_id, rule_model.rule_type, rule_model.source_account_id,
        ) + 1

        if rule_alert_repository.insert_alert_if_absent(
            db_session, user_id, rule_model.id, rule_model.rule_type, "account",
            rule_model.source_account_id, f"E{number}", LEVEL_BREACHED,
        ):
            result.created += 1
    elif not breached and open_episode is not None:
        rule_alert_repository.resolve_episode(db_session, open_episode)
        result.resolved += 1


def _evaluate_account_rules(
    db_session: Session,
    user_id: UUID,
    rules: list[FinancialRuleModel],
    result: AlertEvaluation,
) -> None:
    account_rules = [rule for rule in rules if rule.rule_type in (RULE_FLOOR, RULE_OVERCOMMITMENT)]

    if not account_rules:
        return

    accounts = rule_alert_repository.get_accounts_by_ids(
        db_session, user_id, [rule.source_account_id for rule in account_rules],
    )
    figures = account_service.get_account_alert_figures(
        db_session, user_id, accounts, financial_event_service.server_today(),
    )

    for rule_model in account_rules:
        if rule_model.source_account_id not in figures:
            continue

        reservable, floor, allocation_status = figures[rule_model.source_account_id]

        if rule_model.rule_type == RULE_FLOOR:
            # A floor breach is "reservable below the enabled floor" (the same
            # quantity the manual warning and rule_capacity use). It is NOT an
            # overcommitment, and soft holds never take part in it.
            breached = floor > ZERO and reservable < floor
        else:
            breached = allocation_status == "overcommitted"

        _apply_account_episode(db_session, user_id, rule_model, breached, result)


def _evaluate_budget_rules(
    db_session: Session,
    user_id: UUID,
    rules: list[FinancialRuleModel],
    result: AlertEvaluation,
) -> None:
    budget_rules = {rule.budget_id: rule for rule in rules if rule.rule_type == RULE_BUDGET}

    if not budget_rules:
        return

    items = analytics_service.get_budget_status_for_budgets(
        db_session, user_id, list(budget_rules), financial_event_service.server_today(),
    )

    for item in items:
        rank = BUDGET_LEVEL_RANK.get(item.risk_status)

        # Only an active period can alert; a healthy budget alerts nothing.
        if rank is None or item.period_state != PERIOD_ACTIVE:
            continue

        period_key = item.period_start.isoformat()
        existing = rule_alert_repository.get_budget_levels_for_period(
            db_session, user_id, item.budget_id, period_key,
        )
        highest = max((BUDGET_LEVEL_RANK[level] for level in existing), default=0)

        # Each level at most once per period, and only escalations re-alert: a
        # level at or below one already alerted in this period inserts nothing.
        if rank <= highest:
            continue

        if rule_alert_repository.insert_alert_if_absent(
            db_session, user_id, budget_rules[item.budget_id].id, RULE_BUDGET, "budget",
            item.budget_id, period_key, item.risk_status,
        ):
            result.created += 1


# Evaluates the user's ENABLED alert rules against the CURRENT state, in one
# transaction under L0 (so one user's evaluations are serialized; the unique
# constraints stay the final defense). Idempotent: repeating it with an
# unchanged state changes nothing. Without the E9A table it does nothing.
def evaluate_user_alerts(
    db_session: Session,
    user_id: UUID,
    on_success: Optional[Callable[[Session], None]] = None,
) -> AlertEvaluation:
    result = AlertEvaluation()

    try:
        if not rule_alert_repository.table_exists(db_session):
            db_session.rollback()
            return AlertEvaluation(available=False)

        goal_user_lock.acquire_goal_user_lock(db_session, user_id)
        rules = rule_alert_repository.get_enabled_alert_rules(db_session, user_id)
        _evaluate_account_rules(db_session, user_id, rules, result)
        _evaluate_budget_rules(db_session, user_id, rules, result)

        if on_success is not None:
            # Runs in THIS transaction (the dispatcher records its progress here),
            # so success is committed together with the alert writes or not at all.
            on_success(db_session)

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    return result


# Never raises: used right after an event drain and by the best-effort
# post-response task, where an alert problem must not hide the drain result.
def evaluate_user_alerts_best_effort(
    db_session: Session,
    user_id: UUID,
    on_success: Optional[Callable[[Session], None]] = None,
) -> AlertEvaluation:
    try:
        if on_success is None:
            return evaluate_user_alerts(db_session, user_id)

        return evaluate_user_alerts(db_session, user_id, on_success=on_success)
    except Exception as error:
        logger.error("alert evaluation failed (%s)", type(error).__name__)

        return AlertEvaluation(available=True, failed=True, error_code=type(error).__name__)


def _responses(db_session: Session, user_id: UUID, alerts: list) -> list[RuleAlertResponse]:
    names = rule_alert_repository.get_subject_names(
        db_session, user_id,
        [a.subject_id for a in alerts if a.subject_type == "account"],
        [a.subject_id for a in alerts if a.subject_type == "budget"],
    )

    return [
        RuleAlertResponse.model_validate(alert).model_copy(
            update={"subject_name": names.get(alert.subject_id)}
        )
        for alert in alerts
    ]


def list_alerts(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    acknowledged: Optional[bool] = None,
) -> RuleAlertListResponse:
    if not rule_alert_repository.table_exists(db_session):
        return RuleAlertListResponse(items=[], total=0, limit=limit, offset=offset, available=False)

    alerts, total = rule_alert_repository.list_alerts(db_session, user_id, limit, offset, acknowledged)

    return RuleAlertListResponse(
        items=_responses(db_session, user_id, alerts), total=total, limit=limit, offset=offset,
    )


# Acknowledges one alert (idempotent: the first acknowledgement time is kept).
# A missing or foreign id - and a missing table - is the same 404.
def acknowledge_alert(db_session: Session, alert_id: UUID, user_id: UUID) -> RuleAlertResponse:
    try:
        if not rule_alert_repository.table_exists(db_session):
            raise RuleAlertNotFoundError()

        alert = rule_alert_repository.acknowledge(db_session, user_id, alert_id)

        if alert is None:
            raise RuleAlertNotFoundError()

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    return _responses(db_session, user_id, [alert])[0]
