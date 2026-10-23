from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.accounts import account_repository, account_service
from app.modules.financial_events import financial_event_service
from app.modules.financial_rules import financial_rule_repository, rule_execution_repository
from app.modules.financial_rules.financial_rule_errors import (
    RuleProposalNotFoundError,
    RuleProposalStaleError,
)
from app.modules.financial_rules.financial_rule_models import FinancialRuleModel
from app.modules.financial_rules.rule_execution_models import (
    RuleExecutionItemModel,
    RuleExecutionModel,
)
from app.modules.financial_rules.rule_execution_schemas import (
    RuleProposalItemResponse,
    RuleProposalListResponse,
    RuleProposalResponse,
)
from app.modules.financial_rules.rule_execution_service import (
    AUDIT_APPLIED,
    AUDIT_APPLIED_PARTIAL,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_EXECUTED,
    STATUS_EXECUTED_PARTIAL,
    write_item_transaction,
)
from app.modules.goals import goal_transaction_repository, goal_user_lock
from app.modules.goals.goal_models import GoalModel

ZERO = Decimal("0.00")

AUDIT_CONFIRMED = "confirmed"


# Brings the user's due proposals to `expired` in their own short write
# transaction (lazy expiry, P54). Used by the read endpoint; confirm and reject
# normalize inside their own transaction.
def _normalize_expired(db_session: Session, user_id: UUID) -> None:
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)
        rule_execution_repository.expire_due_proposals(db_session, user_id)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def _proposal_responses(
    db_session: Session, user_id: UUID, executions: list[RuleExecutionModel],
) -> list[RuleProposalResponse]:
    if not executions:
        return []

    ids = [execution.id for execution in executions]
    items_by_execution = rule_execution_repository.get_items_for_executions(db_session, user_id, ids)
    goal_ids = {item.goal_id for items in items_by_execution.values() for item in items}
    goals = {
        goal.id: goal
        for goal in db_session.query(GoalModel)
        .filter(GoalModel.user_id == user_id, GoalModel.id.in_(goal_ids or [None]))
        .all()
    } if goal_ids else {}
    balances = goal_transaction_repository.get_ledger_balances_for_user(db_session, user_id)
    rules = {
        rule.id: rule
        for rule in db_session.query(FinancialRuleModel)
        .filter(
            FinancialRuleModel.user_id == user_id,
            FinancialRuleModel.id.in_({execution.rule_id for execution in executions}),
        )
        .all()
    }

    # confirm_capacity: reservable - floor - prior holds, for awaiting proposals.
    awaiting = [e for e in executions if e.status == STATUS_AWAITING_CONFIRMATION]
    account_ids = {
        item.account_id for e in awaiting for item in items_by_execution.get(e.id, [])
    }
    capacity_inputs: dict[UUID, tuple[Decimal, Decimal, Decimal]] = {}
    hold_entries: list[tuple[UUID, int, Decimal]] = []

    if account_ids:
        account_models = [
            account_repository.get_account_by_id(db_session, account_id, user_id)
            for account_id in sorted(account_ids)
        ]
        capacity_inputs = account_service.get_rule_capacity_inputs(
            db_session, user_id, account_models, financial_event_service.server_today(),
        )
        hold_entries = rule_execution_repository.get_active_hold_entries(
            db_session, user_id, account_ids,
        )

    responses: list[RuleProposalResponse] = []

    for execution in executions:
        items = items_by_execution.get(execution.id, [])
        planned_total = sum((item.planned_amount for item in items), ZERO)
        account_id = items[0].account_id if items else execution.source_account_id
        confirm_capacity: Optional[Decimal] = None

        if execution.status == STATUS_AWAITING_CONFIRMATION and account_id in capacity_inputs:
            reservable, floor, _ = capacity_inputs[account_id]
            prior = sum(
                (
                    amount for entry_account, sequence, amount in hold_entries
                    if entry_account == account_id and sequence < execution.hold_sequence
                ),
                ZERO,
            )
            confirm_capacity = reservable - floor - prior

        rule = rules.get(execution.rule_id)
        responses.append(
            RuleProposalResponse(
                id=execution.id,
                rule_id=execution.rule_id,
                rule_name=rule.name if rule is not None else "",
                rule_version=execution.rule_version,
                status=execution.status,
                reason_code=execution.reason_code,
                partial=bool((execution.params_snapshot or {}).get("proposal_partial", False)),
                hold_sequence=execution.hold_sequence,
                expires_at=execution.expires_at,
                created_at=execution.created_at,
                decided_at=execution.decided_at,
                source_id=execution.source_id,
                source_amount=execution.source_amount,
                source_currency=execution.source_currency,
                source_received_at=execution.source_received_at,
                account_id=account_id,
                currency=execution.source_currency,
                planned_total=planned_total,
                confirm_capacity=confirm_capacity,
                items=[
                    RuleProposalItemResponse(
                        id=item.id,
                        goal_id=item.goal_id,
                        goal_name=goals[item.goal_id].name,
                        position=item.position,
                        planned_amount=item.planned_amount,
                        applied_amount=item.applied_amount,
                        goal_transaction_id=item.goal_transaction_id,
                        target_amount=goals[item.goal_id].target_amount,
                        current_amount=balances.get(item.goal_id, ZERO),
                        expected_amount=(
                            balances.get(item.goal_id, ZERO) + item.planned_amount
                            if execution.status == STATUS_AWAITING_CONFIRMATION
                            else balances.get(item.goal_id, ZERO)
                        ),
                    )
                    for item in items
                ],
            )
        )

    return responses


def list_proposals(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    status: Optional[str] = None,
) -> RuleProposalListResponse:
    _normalize_expired(db_session, user_id)
    executions, total = rule_execution_repository.list_proposals(
        db_session, user_id, limit, offset, status=status,
    )

    return RuleProposalListResponse(
        items=_proposal_responses(db_session, user_id, executions),
        total=total, limit=limit, offset=offset,
    )


def _one_response(db_session: Session, user_id: UUID, execution_id: UUID) -> RuleProposalResponse:
    execution = rule_execution_repository.get_proposal(db_session, user_id, execution_id)

    if execution is None:
        raise RuleProposalNotFoundError()

    return _proposal_responses(db_session, user_id, [execution])[0]


# Why a locked proposal can no longer be confirmed, or None when it can. The
# frozen amounts are never recalculated and no Income row is read.
def _stale_reason(
    rule_model: Optional[FinancialRuleModel],
    execution: RuleExecutionModel,
    items: list[RuleExecutionItemModel],
    goals: dict[UUID, GoalModel],
    account: Optional[object],
    confirm_capacity: Optional[Decimal],
) -> Optional[str]:
    if rule_model is None or rule_model.status != "enabled":
        return "rule_inactive"

    if rule_model.version != execution.rule_version:
        return "rule_changed"

    if account is None or getattr(account, "status") == "archived":
        return "account_unavailable"

    if any(item.goal_id not in goals or goals[item.goal_id].status == "archived" for item in items):
        return "goal_unavailable"

    if getattr(account, "currency") != execution.source_currency or any(
        goals[item.goal_id].currency != getattr(account, "currency") for item in items
    ):
        return "currency_mismatch"

    total = sum((item.planned_amount for item in items), ZERO)

    if confirm_capacity is None or confirm_capacity < total:
        return "insufficient_capacity"

    return None


# Confirms a proposal atomically (§11.4). Lock order: L0 -> execution -> Goals
# (ascending id) -> Account. Terminal proposals return their stored state with
# no second effect. A proposal that fails revalidation is committed as
# cancelled (stale) FIRST and only then reported as a controlled 409, so the
# terminal transition is never rolled back with the error.
def confirm_proposal(db_session: Session, proposal_id: UUID, user_id: UUID) -> RuleProposalResponse:
    stale = False

    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)
        rule_execution_repository.expire_due_proposals(db_session, user_id)
        execution = rule_execution_repository.get_proposal_for_update(db_session, user_id, proposal_id)

        if execution is None:
            raise RuleProposalNotFoundError()

        if execution.status == STATUS_AWAITING_CONFIRMATION:
            items = rule_execution_repository.get_items_for_execution(db_session, user_id, execution.id)
            goals = rule_execution_repository.get_goals_for_update(
                db_session, user_id, [item.goal_id for item in items],
            )
            accounts = account_repository.get_accounts_by_ids_for_update(
                db_session, [item.account_id for item in items], user_id,
            )
            account = accounts.get(items[0].account_id) if items else None
            rule_model = financial_rule_repository.get_rule_by_id_or_none(
                db_session, execution.rule_id, user_id,
            )
            today = financial_event_service.server_today()
            confirm_capacity: Optional[Decimal] = None

            if account is not None:
                reservable, floor, _ = account_service.get_rule_capacity_inputs(
                    db_session, user_id, [account], today,
                )[account.id]
                prior = sum(
                    (
                        amount
                        for entry_account, sequence, amount in rule_execution_repository.get_active_hold_entries(
                            db_session, user_id, [account.id],
                        )
                        if entry_account == account.id and sequence < execution.hold_sequence
                    ),
                    ZERO,
                )
                confirm_capacity = reservable - floor - prior

            reason = _stale_reason(rule_model, execution, items, goals, account, confirm_capacity)

            if reason is not None:
                rule_execution_repository.cancel_proposal(
                    db_session, execution, rule_execution_repository.CANCEL_STALE,
                )
                stale = True
            else:
                _apply_proposal(db_session, user_id, execution, items, goals, rule_model, today)

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    if stale:
        raise RuleProposalStaleError()

    return _one_response(db_session, user_id, proposal_id)


def _apply_proposal(
    db_session: Session,
    user_id: UUID,
    execution: RuleExecutionModel,
    items: list[RuleExecutionItemModel],
    goals: dict[UUID, GoalModel],
    rule_model: Optional[FinancialRuleModel],
    today: date,
) -> None:
    description = f"Confirmed allocation: {rule_model.name if rule_model is not None else ''}"

    for item in items:
        write_item_transaction(
            db_session, user_id, execution, item, goals[item.goal_id], description,
            item.planned_amount, today,
        )

    partial = bool((execution.params_snapshot or {}).get("proposal_partial", False))
    status = STATUS_EXECUTED_PARTIAL if partial else STATUS_EXECUTED
    rule_execution_repository.mark_confirmed(db_session, execution, status)
    rule_execution_repository.add_audit(
        db_session, user_id, execution.id, AUDIT_CONFIRMED, None, actor="user",
    )
    rule_execution_repository.add_audit(
        db_session, user_id, execution.id,
        AUDIT_APPLIED_PARTIAL if partial else AUDIT_APPLIED, None,
    )


# Rejects an awaiting proposal (final). A terminal proposal returns its stored
# state; reject never writes a financial row.
def reject_proposal(db_session: Session, proposal_id: UUID, user_id: UUID) -> RuleProposalResponse:
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)
        rule_execution_repository.expire_due_proposals(db_session, user_id)
        execution = rule_execution_repository.get_proposal_for_update(db_session, user_id, proposal_id)

        if execution is None:
            raise RuleProposalNotFoundError()

        if execution.status == STATUS_AWAITING_CONFIRMATION:
            rule_execution_repository.reject_proposal(db_session, execution)

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    return _one_response(db_session, user_id, proposal_id)


def get_proposal(db_session: Session, proposal_id: UUID, user_id: UUID) -> RuleProposalResponse:
    _normalize_expired(db_session, user_id)

    return _one_response(db_session, user_id, proposal_id)
