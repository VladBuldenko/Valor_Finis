from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.goals.goal_models import GoalModel
from app.modules.financial_rules.financial_rule_models import FinancialRuleModel
from app.modules.financial_rules.financial_rule_schemas import RULE_TYPE_INCOME_ALLOCATION
from app.modules.financial_rules.rule_execution_models import (
    RuleExecutionAuditModel,
    RuleExecutionItemModel,
    RuleExecutionModel,
)

SOURCE_TYPE_INCOME = "income"

STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"


# Enabled INCOME_ALLOCATION rules of the user in the approved evaluation
# order (APPROVED P28): execution_order, created_at, id. Draft, paused and
# disabled rules are never evaluated.
def get_enabled_allocation_rules(
    db_session: Session, user_id: UUID,
) -> list[FinancialRuleModel]:
    return (
        db_session.query(FinancialRuleModel)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.rule_type == RULE_TYPE_INCOME_ALLOCATION,
            FinancialRuleModel.status == "enabled",
        )
        .order_by(
            FinancialRuleModel.execution_order.asc(),
            FinancialRuleModel.created_at.asc(),
            FinancialRuleModel.id.asc(),
        )
        .all()
    )


# Locks and returns the committed executions of one source, keyed by rule id.
# This is the exactly-once lookup (E10): a committed row means the decision is
# final and the event is a replay for that rule.
def get_executions_for_source_for_update(
    db_session: Session, user_id: UUID, source_id: UUID,
) -> dict[UUID, RuleExecutionModel]:
    rows = (
        db_session.query(RuleExecutionModel)
        .filter(
            RuleExecutionModel.user_id == user_id,
            RuleExecutionModel.source_type == SOURCE_TYPE_INCOME,
            RuleExecutionModel.source_id == source_id,
        )
        .order_by(RuleExecutionModel.id)
        .with_for_update()
        .all()
    )

    return {row.rule_id: row for row in rows}


def add_execution(
    db_session: Session, execution_model: RuleExecutionModel,
) -> RuleExecutionModel:
    db_session.add(execution_model)
    db_session.flush()

    return execution_model


def add_item(db_session: Session, item_model: RuleExecutionItemModel) -> RuleExecutionItemModel:
    db_session.add(item_model)
    db_session.flush()

    return item_model


def add_audit(
    db_session: Session,
    user_id: UUID,
    execution_id: UUID,
    code: str,
    related_event_id: Optional[UUID],
    details: Optional[dict[str, Any]] = None,
    actor: str = "system",
) -> RuleExecutionAuditModel:
    audit_model = RuleExecutionAuditModel(
        user_id=user_id,
        execution_id=execution_id,
        code=code,
        actor=actor,
        related_event_id=related_event_id,
        details=details,
        # clock_timestamp(), not the transaction's now(): several entries of one
        # transaction (proposed / confirmed / applied) must keep their order.
        created_at=func.clock_timestamp(),
    )
    db_session.add(audit_model)
    db_session.flush()

    return audit_model


# Whether an audit annotation of this code already exists for the event, so a
# re-delivered event never appends a duplicate annotation.
def audit_exists(
    db_session: Session,
    user_id: UUID,
    execution_id: UUID,
    code: str,
    related_event_id: UUID,
) -> bool:
    return (
        db_session.query(RuleExecutionAuditModel.id)
        .filter(
            RuleExecutionAuditModel.user_id == user_id,
            RuleExecutionAuditModel.execution_id == execution_id,
            RuleExecutionAuditModel.code == code,
            RuleExecutionAuditModel.related_event_id == related_event_id,
        )
        .first()
        is not None
    )


def get_items_for_executions(
    db_session: Session, user_id: UUID, execution_ids: Sequence[UUID],
) -> dict[UUID, list[RuleExecutionItemModel]]:
    grouped: dict[UUID, list[RuleExecutionItemModel]] = {}

    if not execution_ids:
        return grouped

    rows = (
        db_session.query(RuleExecutionItemModel)
        .filter(
            RuleExecutionItemModel.user_id == user_id,
            RuleExecutionItemModel.execution_id.in_(list(execution_ids)),
        )
        .order_by(RuleExecutionItemModel.position.asc(), RuleExecutionItemModel.id.asc())
        .all()
    )

    for row in rows:
        grouped.setdefault(row.execution_id, []).append(row)

    return grouped


def get_audit_for_executions(
    db_session: Session, user_id: UUID, execution_ids: Sequence[UUID],
) -> dict[UUID, list[RuleExecutionAuditModel]]:
    grouped: dict[UUID, list[RuleExecutionAuditModel]] = {}

    if not execution_ids:
        return grouped

    rows = (
        db_session.query(RuleExecutionAuditModel)
        .filter(
            RuleExecutionAuditModel.user_id == user_id,
            RuleExecutionAuditModel.execution_id.in_(list(execution_ids)),
        )
        .order_by(RuleExecutionAuditModel.created_at.asc(), RuleExecutionAuditModel.id.asc())
        .all()
    )

    for row in rows:
        grouped.setdefault(row.execution_id, []).append(row)

    return grouped


def list_executions(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    rule_id: Optional[UUID] = None,
    status: Optional[str] = None,
) -> tuple[list[RuleExecutionModel], int]:
    query = db_session.query(RuleExecutionModel).filter(RuleExecutionModel.user_id == user_id)

    if rule_id is not None:
        query = query.filter(RuleExecutionModel.rule_id == rule_id)

    if status is not None:
        query = query.filter(RuleExecutionModel.status == status)

    total = query.count()
    rows = (
        query.order_by(RuleExecutionModel.created_at.desc(), RuleExecutionModel.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return rows, total


# Active soft holds per Account (APPROVED P55): planned amounts of
# awaiting_confirmation proposals that have not expired. An expired proposal
# is excluded even before its state is normalized. Proposals only exist from
# VF-020E8; until then this is always zero.
def get_active_holds_for_accounts(
    db_session: Session, user_id: UUID, account_ids: Iterable[UUID],
) -> dict[UUID, Decimal]:
    ids = list(account_ids)

    if not ids:
        return {}

    rows = (
        db_session.query(
            RuleExecutionItemModel.account_id,
            func.coalesce(func.sum(RuleExecutionItemModel.planned_amount), 0),
        )
        .join(
            RuleExecutionModel,
            (RuleExecutionModel.id == RuleExecutionItemModel.execution_id)
            & (RuleExecutionModel.user_id == RuleExecutionItemModel.user_id),
        )
        .filter(
            RuleExecutionItemModel.user_id == user_id,
            RuleExecutionItemModel.account_id.in_(ids),
            RuleExecutionModel.status == STATUS_AWAITING_CONFIRMATION,
            RuleExecutionModel.expires_at > func.now(),
        )
        .group_by(RuleExecutionItemModel.account_id)
        .all()
    )

    return {account_id: Decimal(total) for account_id, total in rows}


def rule_has_executions(db_session: Session, rule_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(RuleExecutionModel.id)
        .filter(RuleExecutionModel.user_id == user_id, RuleExecutionModel.rule_id == rule_id)
        .first()
        is not None
    )


def goal_has_execution_items(db_session: Session, goal_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(RuleExecutionItemModel.id)
        .filter(RuleExecutionItemModel.user_id == user_id, RuleExecutionItemModel.goal_id == goal_id)
        .first()
        is not None
    )


def account_has_execution_items(db_session: Session, account_id: UUID, user_id: UUID) -> bool:
    return (
        db_session.query(RuleExecutionItemModel.id)
        .filter(
            RuleExecutionItemModel.user_id == user_id,
            RuleExecutionItemModel.account_id == account_id,
        )
        .first()
        is not None
    )


# Locks the given Goals FOR UPDATE in ascending id order (global lock level
# L2). Only the user's own Goals are returned, so a foreign id can never be
# locked or read.
# The same Goals as get_goals_for_update, read without row locks. Used by the
# read-only preview, which must never lock or write.
def get_goals(
    db_session: Session, user_id: UUID, goal_ids: Iterable[UUID],
) -> dict[UUID, GoalModel]:
    ids = sorted(set(goal_ids))

    if not ids:
        return {}

    rows = (
        db_session.query(GoalModel)
        .filter(GoalModel.user_id == user_id, GoalModel.id.in_(ids))
        .order_by(GoalModel.id)
        .all()
    )

    return {row.id: row for row in rows}


def get_goals_for_update(
    db_session: Session, user_id: UUID, goal_ids: Iterable[UUID],
) -> dict[UUID, GoalModel]:
    ids = sorted(set(goal_ids))

    if not ids:
        return {}

    rows = (
        db_session.query(GoalModel)
        .filter(GoalModel.user_id == user_id, GoalModel.id.in_(ids))
        .order_by(GoalModel.id)
        .with_for_update()
        .all()
    )

    return {row.id: row for row in rows}


# ------------------------------------------------------------------
# CONFIRM proposals (VF-020E8)
# ------------------------------------------------------------------

# Cancellation reason codes (§11.5).
CANCEL_SUPERSEDED = "superseded"
CANCEL_STALE = "stale"
CANCEL_SOURCE_CHANGED = "source_changed"
CANCEL_SOURCE_DELETED = "source_deleted"
CANCEL_RULE_INACTIVE = "rule_inactive"


# Takes the next permanent hold position (APPROVED P80). Called exactly once
# per proposal, under L0; a rollback leaves a harmless gap.
def next_hold_sequence(db_session: Session) -> int:
    return int(db_session.execute(select(func.nextval("rule_execution_hold_sequence"))).scalar_one())


# Locks and returns one of the user's PROPOSALS (an execution that ever had a
# hold_sequence). A foreign id, a missing id and a non-proposal execution are
# all None, so the caller can answer an indistinguishable 404.
def get_proposal_for_update(
    db_session: Session, user_id: UUID, execution_id: UUID,
) -> Optional[RuleExecutionModel]:
    return (
        db_session.query(RuleExecutionModel)
        .filter(
            RuleExecutionModel.id == execution_id,
            RuleExecutionModel.user_id == user_id,
            RuleExecutionModel.hold_sequence.isnot(None),
        )
        .with_for_update()
        .first()
    )


def _append_terminal(
    db_session: Session,
    execution: RuleExecutionModel,
    status: str,
    audit_code: str,
    reason_code: Optional[str],
    related_event_id: Optional[UUID],
    actor: str,
) -> None:
    execution.status = status
    execution.reason_code = reason_code
    execution.decided_at = func.now()
    db_session.flush()
    add_audit(
        db_session,
        user_id=execution.user_id,
        execution_id=execution.id,
        code=audit_code,
        related_event_id=related_event_id,
        details={"reason_code": reason_code} if reason_code else None,
        actor=actor,
    )


# Ends the hold of one locked proposal by cancelling it with a stable reason.
def cancel_proposal(
    db_session: Session,
    execution: RuleExecutionModel,
    reason_code: str,
    related_event_id: Optional[UUID] = None,
    actor: str = "system",
) -> None:
    _append_terminal(
        db_session, execution, "cancelled", "cancelled", reason_code, related_event_id, actor,
    )


# Cancels every open (awaiting_confirmation) proposal of a rule or of a source,
# row-locking them in id order first. Idempotent: a terminal proposal is never
# touched. Returns the number of proposals cancelled.
def cancel_open_proposals(
    db_session: Session,
    user_id: UUID,
    reason_code: str,
    rule_id: Optional[UUID] = None,
    source_id: Optional[UUID] = None,
    related_event_id: Optional[UUID] = None,
) -> int:
    query = db_session.query(RuleExecutionModel).filter(
        RuleExecutionModel.user_id == user_id,
        RuleExecutionModel.status == STATUS_AWAITING_CONFIRMATION,
    )

    if rule_id is not None:
        query = query.filter(RuleExecutionModel.rule_id == rule_id)

    if source_id is not None:
        query = query.filter(
            RuleExecutionModel.source_type == SOURCE_TYPE_INCOME,
            RuleExecutionModel.source_id == source_id,
        )

    rows = query.order_by(RuleExecutionModel.id).with_for_update().all()

    for execution in rows:
        cancel_proposal(db_session, execution, reason_code, related_event_id)

    return len(rows)


# Lazily normalizes the user's due proposals to `expired` (APPROVED P54). A
# proposal stops counting as a hold the moment expires_at passes (the hold
# query filters on it), so this only brings the stored state in line. Idempotent.
def expire_due_proposals(db_session: Session, user_id: UUID) -> int:
    rows = (
        db_session.query(RuleExecutionModel)
        .filter(
            RuleExecutionModel.user_id == user_id,
            RuleExecutionModel.status == STATUS_AWAITING_CONFIRMATION,
            RuleExecutionModel.expires_at <= func.now(),
        )
        .order_by(RuleExecutionModel.id)
        .with_for_update()
        .all()
    )

    for execution in rows:
        _append_terminal(db_session, execution, "expired", "expired", None, None, "system")

    return len(rows)


def reject_proposal(db_session: Session, execution: RuleExecutionModel) -> None:
    _append_terminal(db_session, execution, "rejected", "rejected", None, None, "user")


# Active hold entries (account_id, hold_sequence, amount) of unexpired
# awaiting proposals, for prior_holds(A, X) (§8.1): the caller sums the entries
# of the same Account whose hold_sequence is below X's. Own and later holds are
# excluded by the sequence comparison alone.
def get_active_hold_entries(
    db_session: Session, user_id: UUID, account_ids: Iterable[UUID],
) -> list[tuple[UUID, int, Decimal]]:
    ids = list(account_ids)

    if not ids:
        return []

    rows = (
        db_session.query(
            RuleExecutionItemModel.account_id,
            RuleExecutionModel.hold_sequence,
            func.coalesce(func.sum(RuleExecutionItemModel.planned_amount), 0),
        )
        .join(
            RuleExecutionModel,
            (RuleExecutionModel.id == RuleExecutionItemModel.execution_id)
            & (RuleExecutionModel.user_id == RuleExecutionItemModel.user_id),
        )
        .filter(
            RuleExecutionItemModel.user_id == user_id,
            RuleExecutionItemModel.account_id.in_(ids),
            RuleExecutionModel.status == STATUS_AWAITING_CONFIRMATION,
            RuleExecutionModel.expires_at > func.now(),
        )
        .group_by(RuleExecutionItemModel.account_id, RuleExecutionModel.hold_sequence)
        .all()
    )

    return [(account_id, int(sequence), Decimal(total)) for account_id, sequence, total in rows]


def list_proposals(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    status: Optional[str] = None,
) -> tuple[list[RuleExecutionModel], int]:
    query = db_session.query(RuleExecutionModel).filter(
        RuleExecutionModel.user_id == user_id,
        RuleExecutionModel.hold_sequence.isnot(None),
    )

    if status is not None:
        query = query.filter(RuleExecutionModel.status == status)

    total = query.count()
    rows = (
        query.order_by(RuleExecutionModel.hold_sequence.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return rows, total


def get_proposal(
    db_session: Session, user_id: UUID, execution_id: UUID,
) -> Optional[RuleExecutionModel]:
    return (
        db_session.query(RuleExecutionModel)
        .filter(
            RuleExecutionModel.id == execution_id,
            RuleExecutionModel.user_id == user_id,
            RuleExecutionModel.hold_sequence.isnot(None),
        )
        .first()
    )


def mark_confirmed(db_session: Session, execution: RuleExecutionModel, status: str) -> None:
    execution.status = status
    execution.reason_code = None
    execution.decided_at = func.now()
    db_session.flush()


def get_items_for_execution(
    db_session: Session, user_id: UUID, execution_id: UUID,
) -> list[RuleExecutionItemModel]:
    return get_items_for_executions(db_session, user_id, [execution_id]).get(execution_id, [])
