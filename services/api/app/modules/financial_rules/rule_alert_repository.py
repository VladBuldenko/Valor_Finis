from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.financial_rules.financial_rule_models import FinancialRuleModel
from app.modules.financial_rules.rule_alert_models import RuleAlertModel

ALERT_RULE_TYPES = ("MINIMUM_UNALLOCATED_FLOOR", "OVERCOMMITMENT_ALERT", "BUDGET_ALERT")


# Whether the E9A table exists in the connected database. The runtime is
# deployed before the production migration is applied, so every alert code path
# first asks; a missing table means "alerts not available yet", never an error.
def table_exists(db_session: Session) -> bool:
    return bool(
        db_session.execute(text("SELECT to_regclass('public.rule_alerts') IS NOT NULL")).scalar_one()
    )


# The user's ENABLED alert rules (floor, overcommitment, Budget), id order.
def get_enabled_alert_rules(db_session: Session, user_id: UUID) -> list[FinancialRuleModel]:
    return (
        db_session.query(FinancialRuleModel)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.status == "enabled",
            FinancialRuleModel.rule_type.in_(ALERT_RULE_TYPES),
        )
        .order_by(FinancialRuleModel.id)
        .all()
    )


# Inserts one alert; a duplicate of the alert key or of the open Account
# episode is silently skipped (ON CONFLICT DO NOTHING), because the unique
# constraints are the final concurrency defense. Returns True when a row was
# inserted.
def insert_alert_if_absent(
    db_session: Session,
    user_id: UUID,
    rule_id: Optional[UUID],
    rule_type: str,
    subject_type: str,
    subject_id: UUID,
    period_key: str,
    level: str,
) -> bool:
    result = db_session.execute(
        pg_insert(RuleAlertModel)
        .values(
            id=uuid4(), user_id=user_id, rule_id=rule_id, rule_type=rule_type,
            subject_type=subject_type, subject_id=subject_id, period_key=period_key,
            level=level,
        )
        .on_conflict_do_nothing()
        .returning(RuleAlertModel.id)
    )

    return result.first() is not None


def get_open_episode(
    db_session: Session, user_id: UUID, rule_type: str, subject_id: UUID,
) -> Optional[RuleAlertModel]:
    return (
        db_session.query(RuleAlertModel)
        .filter(
            RuleAlertModel.user_id == user_id,
            RuleAlertModel.rule_type == rule_type,
            RuleAlertModel.subject_id == subject_id,
            RuleAlertModel.resolved_at.is_(None),
        )
        .with_for_update()
        .first()
    )


# Highest episode number ever used for the Account and alert type (0 if none).
def get_last_episode_number(
    db_session: Session, user_id: UUID, rule_type: str, subject_id: UUID,
) -> int:
    value = db_session.execute(
        select(func.coalesce(func.max(cast(func.substr(RuleAlertModel.period_key, 2), Integer)), 0))
        .where(
            RuleAlertModel.user_id == user_id,
            RuleAlertModel.rule_type == rule_type,
            RuleAlertModel.subject_id == subject_id,
        )
    ).scalar_one()

    return int(value)


def resolve_episode(db_session: Session, alert: RuleAlertModel) -> None:
    alert.resolved_at = func.now()
    db_session.flush()


def get_budget_levels_for_period(
    db_session: Session, user_id: UUID, budget_id: UUID, period_key: str,
) -> set[str]:
    rows = db_session.query(RuleAlertModel.level).filter(
        RuleAlertModel.user_id == user_id,
        RuleAlertModel.rule_type == "BUDGET_ALERT",
        RuleAlertModel.subject_id == budget_id,
        RuleAlertModel.period_key == period_key,
    ).all()

    return {level for (level,) in rows}


def list_alerts(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    acknowledged: Optional[bool] = None,
) -> tuple[list[RuleAlertModel], int]:
    query = db_session.query(RuleAlertModel).filter(RuleAlertModel.user_id == user_id)

    if acknowledged is True:
        query = query.filter(RuleAlertModel.acknowledged_at.isnot(None))
    elif acknowledged is False:
        query = query.filter(RuleAlertModel.acknowledged_at.is_(None))

    total = query.count()
    rows = (
        query.order_by(RuleAlertModel.created_at.desc(), RuleAlertModel.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return rows, total


def get_alert(db_session: Session, user_id: UUID, alert_id: UUID) -> Optional[RuleAlertModel]:
    return (
        db_session.query(RuleAlertModel)
        .filter(RuleAlertModel.id == alert_id, RuleAlertModel.user_id == user_id)
        .first()
    )


# Acknowledges an alert once: the conditional UPDATE keeps the first
# acknowledgement time, so a repeated call is a no-op. Returns the alert.
def acknowledge(db_session: Session, user_id: UUID, alert_id: UUID) -> Optional[RuleAlertModel]:
    db_session.execute(
        text(
            "UPDATE rule_alerts SET acknowledged_at = now() "
            "WHERE id = :alert_id AND user_id = :user_id AND acknowledged_at IS NULL"
        ),
        {"alert_id": alert_id, "user_id": user_id},
    )
    db_session.expire_all()

    return get_alert(db_session, user_id, alert_id)


def get_accounts_by_ids(db_session: Session, user_id: UUID, account_ids: list[UUID]) -> list:
    from app.modules.accounts.account_models import AccountModel

    if not account_ids:
        return []

    return (
        db_session.query(AccountModel)
        .filter(AccountModel.user_id == user_id, AccountModel.id.in_(account_ids))
        .order_by(AccountModel.id)
        .all()
    )


def get_subject_names(
    db_session: Session, user_id: UUID, account_ids: list[UUID], budget_ids: list[UUID],
) -> dict[UUID, str]:
    from app.modules.accounts.account_models import AccountModel
    from app.modules.budgets.budgets_models import BudgetModel

    names: dict[UUID, str] = {}

    if account_ids:
        for account_id, name in db_session.query(AccountModel.id, AccountModel.name).filter(
            AccountModel.user_id == user_id, AccountModel.id.in_(account_ids),
        ):
            names[account_id] = name

    if budget_ids:
        for budget_id, name in db_session.query(BudgetModel.id, BudgetModel.name).filter(
            BudgetModel.user_id == user_id, BudgetModel.id.in_(budget_ids),
        ):
            names[budget_id] = name

    return names


# Cross-user discovery for the periodic dispatcher (VF-020E10): users with at
# least one ENABLED alert rule (floor, overcommitment, Budget), independent of
# any Income event. Reads only financial_rules.
def count_users_with_enabled_alert_rules(db_session: Session) -> int:
    return int(
        db_session.execute(
            text(
                "SELECT count(DISTINCT user_id) FROM financial_rules "
                "WHERE status = 'enabled' AND rule_type IN "
                "('MINIMUM_UNALLOCATED_FLOOR', 'OVERCOMMITMENT_ALERT', 'BUDGET_ALERT')"
            )
        ).scalar_one()
    )


# A per-run RANDOM SAMPLE of those users: ordered by md5(user_id || seed) with a
# fresh seed for every dispatcher run, then cut at `limit`. There is no cursor, no
# page index and no dependence on the clock, so (1) a run that stops early always
# evaluated a uniformly random prefix, never the same tail-starved prefix, and (2)
# skipped, delayed or doubled scheduler ticks cannot leave any user unvisited.
# This gives almost-sure (probabilistic) liveness, NOT a deterministic bound; a
# deterministic bound needs persisted progress (see docs/operations/rule-dispatcher.md).
def get_users_with_enabled_alert_rules_sample(
    db_session: Session, limit: int, seed: str,
) -> list[UUID]:
    rows = db_session.execute(
        text(
            "SELECT user_id FROM (SELECT DISTINCT user_id FROM financial_rules "
            "WHERE status = 'enabled' AND rule_type IN "
            "('MINIMUM_UNALLOCATED_FLOOR', 'OVERCOMMITMENT_ALERT', 'BUDGET_ALERT')) AS alert_users "
            "ORDER BY md5(user_id::text || :seed), user_id LIMIT :limit"
        ),
        {"limit": limit, "seed": seed},
    ).all()

    return [row[0] for row in rows]
