from decimal import Decimal
from typing import Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.financial_rules.financial_rule_errors import FinancialRuleNotFoundError
from app.modules.financial_rules.financial_rule_models import (
    FinancialRuleGoalTargetModel,
    FinancialRuleModel,
)
from app.modules.financial_rules.financial_rule_schemas import (
    RULE_TYPE_FLOOR,
    RULE_TYPE_INCOME_ALLOCATION,
)

# Persistence for financial_rules and financial_rule_goal_targets (VF-020E5).
# Every query is scoped by user_id. No function here commits: the service owns
# the single transaction (and takes the user lock L0 first for every write).
# Nothing in this module reads rule executions, holds, alerts or events - none
# of those tables is queried by VF-020E5.


def get_rule_by_id(db_session: Session, rule_id: UUID, user_id: UUID) -> FinancialRuleModel:
    rule_model = (
        db_session.query(FinancialRuleModel)
        .filter(FinancialRuleModel.id == rule_id, FinancialRuleModel.user_id == user_id)
        .first()
    )

    if rule_model is None:
        raise FinancialRuleNotFoundError()

    return rule_model


def get_rule_by_id_for_update(
    db_session: Session, rule_id: UUID, user_id: UUID,
) -> FinancialRuleModel:
    rule_model = (
        db_session.query(FinancialRuleModel)
        .filter(FinancialRuleModel.id == rule_id, FinancialRuleModel.user_id == user_id)
        .with_for_update()
        .first()
    )

    if rule_model is None:
        raise FinancialRuleNotFoundError()

    return rule_model


# Lists the user's rules: allocation rules first in evaluation order
# (execution_order, created_at, id), then the other rules by creation time.
# The order is presentational in VF-020E5 - nothing executes.
def get_rules(db_session: Session, user_id: UUID) -> list[FinancialRuleModel]:
    return (
        db_session.query(FinancialRuleModel)
        .filter(FinancialRuleModel.user_id == user_id)
        .order_by(
            (FinancialRuleModel.rule_type != RULE_TYPE_INCOME_ALLOCATION),
            FinancialRuleModel.execution_order.asc().nulls_last(),
            FinancialRuleModel.created_at.asc(),
            FinancialRuleModel.id.asc(),
        )
        .all()
    )


# Loads the targets of several rules with ONE query (no N+1), ordered by the
# configuration position and id.
def get_targets_for_rules(
    db_session: Session, user_id: UUID, rule_ids: Sequence[UUID],
) -> dict[UUID, list[FinancialRuleGoalTargetModel]]:
    grouped: dict[UUID, list[FinancialRuleGoalTargetModel]] = {}

    if not rule_ids:
        return grouped

    rows = (
        db_session.query(FinancialRuleGoalTargetModel)
        .filter(
            FinancialRuleGoalTargetModel.user_id == user_id,
            FinancialRuleGoalTargetModel.rule_id.in_(list(rule_ids)),
        )
        .order_by(FinancialRuleGoalTargetModel.position.asc(), FinancialRuleGoalTargetModel.id.asc())
        .all()
    )

    for row in rows:
        grouped.setdefault(row.rule_id, []).append(row)

    return grouped


# COALESCE(MAX(execution_order), 0) + 1 over the user's allocation rules.
# Callers hold the user lock L0, which serializes concurrent creates.
def get_next_execution_order(db_session: Session, user_id: UUID) -> int:
    maximum = (
        db_session.query(func.coalesce(func.max(FinancialRuleModel.execution_order), 0))
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.rule_type == RULE_TYPE_INCOME_ALLOCATION,
        )
        .scalar()
    )

    return int(maximum) + 1


# True when another rule of a one-per-subject type already exists.
def subject_rule_exists(
    db_session: Session,
    user_id: UUID,
    rule_type: str,
    source_account_id: Optional[UUID],
    budget_id: Optional[UUID],
    exclude_rule_id: Optional[UUID] = None,
) -> bool:
    query = db_session.query(FinancialRuleModel.id).filter(
        FinancialRuleModel.user_id == user_id,
        FinancialRuleModel.rule_type == rule_type,
        FinancialRuleModel.source_account_id == source_account_id
        if source_account_id is not None
        else FinancialRuleModel.budget_id == budget_id,
    )

    if exclude_rule_id is not None:
        query = query.filter(FinancialRuleModel.id != exclude_rule_id)

    return query.first() is not None


def add_rule(db_session: Session, rule_model: FinancialRuleModel) -> FinancialRuleModel:
    db_session.add(rule_model)
    db_session.flush()
    db_session.refresh(rule_model)

    return rule_model


def add_target(
    db_session: Session, target_model: FinancialRuleGoalTargetModel,
) -> FinancialRuleGoalTargetModel:
    db_session.add(target_model)

    return target_model


def delete_target(db_session: Session, target_model: FinancialRuleGoalTargetModel) -> None:
    db_session.delete(target_model)


def delete_rule(db_session: Session, rule_model: FinancialRuleModel) -> None:
    db_session.delete(rule_model)
    db_session.flush()


# The ENABLED floor of each given Account, in one grouped query. Accounts
# without an enabled floor are absent from the result (callers use 0.00).
def get_enabled_floors_for_accounts(
    db_session: Session, user_id: UUID, account_ids: Iterable[UUID],
) -> dict[UUID, Decimal]:
    ids = list(account_ids)

    if not ids:
        return {}

    rows = (
        db_session.query(FinancialRuleModel.source_account_id, FinancialRuleModel.floor_amount)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.rule_type == RULE_TYPE_FLOOR,
            FinancialRuleModel.status == "enabled",
            FinancialRuleModel.source_account_id.in_(ids),
        )
        .all()
    )

    return {account_id: floor_amount for account_id, floor_amount in rows}


def get_enabled_floor_for_account(
    db_session: Session, user_id: UUID, account_id: UUID,
) -> Decimal:
    floors = get_enabled_floors_for_accounts(db_session, user_id, [account_id])

    return floors.get(account_id, Decimal("0.00"))


# Lifecycle reference checks (VF-020E5, P57). Plain reads: the caller holds
# the referenced row lock (Account / Budget) or the user lock L0 (Goal).
def account_is_referenced_by_rule(db_session: Session, account_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(FinancialRuleModel.id)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.source_account_id == account_id,
        )
        .first()
        is not None
    )


def goal_is_referenced_by_rule_target(db_session: Session, goal_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(FinancialRuleGoalTargetModel.id)
        .filter(
            FinancialRuleGoalTargetModel.user_id == user_id,
            FinancialRuleGoalTargetModel.goal_id == goal_id,
        )
        .first()
        is not None
    )


def budget_is_referenced_by_rule(db_session: Session, budget_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(FinancialRuleModel.id)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.budget_id == budget_id,
        )
        .first()
        is not None
    )
