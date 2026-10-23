from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session

from app.modules.accounts import account_repository, account_service
from app.modules.accounts.account_models import AccountModel
from app.modules.financial_events import financial_event_service
from app.modules.financial_events.financial_event_models import FinancialEventModel
from app.modules.financial_rules import financial_rule_repository, rule_execution_repository
from app.modules.financial_rules.financial_rule_models import (
    FinancialRuleGoalTargetModel,
    FinancialRuleModel,
)
from app.modules.financial_rules.rule_execution_models import (
    RuleExecutionItemModel,
    RuleExecutionModel,
)
from app.modules.financial_rules.rule_execution_schemas import (
    RuleExecutionListResponse,
    RuleExecutionResponse,
)
from app.modules.goals import goal_transaction_repository
from app.modules.goals.goal_models import GoalModel

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

LIVE_ENTRY_WINDOW_DAYS = 7

EVENT_INCOME_CREATED = "income.created"
EVENT_INCOME_UPDATED = "income.updated"
EVENT_INCOME_DELETED = "income.deleted"

STATUS_EXECUTED = "executed"
STATUS_EXECUTED_PARTIAL = "executed_partial"
STATUS_SKIPPED = "skipped"
STATUS_BLOCKED = "blocked"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"

# Absolute 168 hours (not "7 days"): a calendar-day interval would shift by an
# hour across a DST change in the session time zone.
PROPOSAL_LIFETIME_SQL = "interval '168 hours'"

REASON_INSUFFICIENT_CAPACITY = "insufficient_capacity"
REASON_NOTHING_TO_ALLOCATE = "nothing_to_allocate"
REASON_SOURCE_ACCOUNT_ARCHIVED = "source_account_archived"
REASON_TARGET_GOAL_ARCHIVED = "target_goal_archived"
REASON_CURRENCY_MISMATCH = "currency_mismatch"

# Stable, non-monetary "not eligible" codes stored in outcome_summary.
NOT_ELIGIBLE_PROVENANCE = "provenance_not_live"
NOT_ELIGIBLE_ACCOUNT = "income_account_mismatch"
NOT_ELIGIBLE_ACTIVE_SINCE = "created_before_active_since"
NOT_ELIGIBLE_EFFECTIVE_FROM = "received_before_effective_from"
NOT_ELIGIBLE_WINDOW = "received_outside_live_window"
NOT_ELIGIBLE_SOURCE = "income_source_not_selected"
NOT_ELIGIBLE_NO_CREATION_EVENT = "no_creation_event"

AUDIT_PROPOSED = "proposed"
AUDIT_CANCELLED = "cancelled"
AUDIT_APPLIED = "applied"
AUDIT_APPLIED_PARTIAL = "applied_partial"
AUDIT_SKIPPED = "skipped"
AUDIT_BLOCKED = "blocked"
AUDIT_SOURCE_CHANGED = "source_changed"
AUDIT_SOURCE_DELETED = "source_deleted"

MODE_AUTO = "AUTO"
MODE_CONFIRM = "CONFIRM"

POLICY_FIXED = "FIXED_PER_GOAL"
POLICY_PERCENT = "PERCENT_OF_INCOME_WATERFALL"


class EventDeferredError(Exception):
    """
    Raised before any write when the event's business date has not arrived in
    the server's calendar. The processor returns the claim to the queue; this
    is a deferral, never a technical failure and never a retry attempt.
    """

    def __init__(self, not_before: datetime) -> None:
        super().__init__("income event is business-date deferred")
        self.not_before = not_before


class RuleExecutionInvariantError(Exception):
    """
    Raised when an execution's items and GoalTransactions disagree. This is a
    defect, not a business outcome: it is a technical failure, so the whole
    transaction rolls back and nothing partial is ever committed.
    """


@dataclass
class _PlannedItem:
    goal: GoalModel
    position: int
    planned: Decimal


@dataclass
class _OutcomeSummary:
    counts: dict[str, int] = field(default_factory=dict)
    not_eligible: dict[str, int] = field(default_factory=dict)
    replayed: int = 0
    annotated: int = 0

    def count(self, status: str) -> None:
        self.counts[status] = self.counts.get(status, 0) + 1

    def not_eligible_for(self, code: str) -> None:
        self.not_eligible[code] = self.not_eligible.get(code, 0) + 1

    def as_dict(self, event_type: str) -> dict[str, Any]:
        # Non-monetary codes and counters only (APPROVED P83).
        return {
            "event_type": event_type,
            "executions": dict(sorted(self.counts.items())),
            "not_eligible": dict(sorted(self.not_eligible.items())),
            "replayed": self.replayed,
            "annotated": self.annotated,
        }


@dataclass
class _AccountCapacity:
    account: AccountModel
    reservable: Decimal
    floor: Decimal
    holds: Decimal

    @property
    def rule_capacity(self) -> Decimal:
        return self.reservable - self.floor - self.holds


def _event_local_date(event_model: FinancialEventModel) -> date:
    # The server calendar the live-entry classification used (date.today()).
    return event_model.occurred_at.astimezone().date()


def _snapshot_dict(event_model: FinancialEventModel) -> dict[str, Any]:
    return {
        "amount": event_model.snap_amount,
        "currency": event_model.snap_currency,
        "received_at": event_model.snap_received_at,
        "account_id": event_model.snap_account_id,
        "income_source": event_model.snap_income_source,
    }


def _execution_snapshot_dict(execution_model: RuleExecutionModel) -> dict[str, Any]:
    return {
        "amount": execution_model.source_amount,
        "currency": execution_model.source_currency,
        "received_at": execution_model.source_received_at,
        "account_id": execution_model.source_account_id,
        "income_source": execution_model.source_income_source,
    }


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(name for name in before if before[name] != after[name])


def _params_snapshot(
    rule_model: FinancialRuleModel, targets: list[FinancialRuleGoalTargetModel],
) -> dict[str, Any]:
    return {
        "execution_mode": rule_model.execution_mode,
        "execution_order": rule_model.execution_order,
        "policy": rule_model.policy,
        "percent": str(rule_model.percent) if rule_model.percent is not None else None,
        "cap_at_target": rule_model.cap_at_target,
        "allow_partial": rule_model.allow_partial,
        "income_sources": list(rule_model.income_sources or []),
        "effective_from": rule_model.effective_from.isoformat() if rule_model.effective_from else None,
        "source_account_id": str(rule_model.source_account_id),
        "targets": [
            {
                "goal_id": str(target.goal_id),
                "amount_or_cap": (
                    str(target.amount_or_cap) if target.amount_or_cap is not None else None
                ),
                "position": target.position,
            }
            for target in targets
        ],
    }


# Eligibility predicates E2 and E5-E7 (§15.1) for one enabled rule. E1 holds by
# construction (every read is scoped to the event's user), E3 is the business-
# date deferral handled before evaluation, E4 is the provenance check of the
# creation event, E8/E9 are business outcomes decided later, and E10 is the
# committed-execution lookup.
# Parameters:
# - event_model: the event being processed (its snapshot is the source state).
# - creation_event: the Income's income.created event; its provenance and
#   occurred_at decide E4/E5 so an edit can never make an old Income eligible.
# Returns:
# - None when eligible, otherwise the stable not-eligible code.
def _eligibility_failure(
    rule_model: FinancialRuleModel,
    event_model: FinancialEventModel,
    creation_event: FinancialEventModel,
) -> Optional[str]:
    if event_model.snap_account_id != rule_model.source_account_id:
        return NOT_ELIGIBLE_ACCOUNT

    if rule_model.active_since is None or creation_event.occurred_at < rule_model.active_since:
        return NOT_ELIGIBLE_ACTIVE_SINCE

    if (
        rule_model.effective_from is not None
        and event_model.snap_received_at < rule_model.effective_from
    ):
        return NOT_ELIGIBLE_EFFECTIVE_FROM

    window_start = _event_local_date(event_model) - timedelta(days=LIVE_ENTRY_WINDOW_DAYS)

    if event_model.snap_received_at < window_start:
        return NOT_ELIGIBLE_WINDOW

    if event_model.snap_income_source not in (rule_model.income_sources or []):
        return NOT_ELIGIBLE_SOURCE

    return None


def _is_live_manual(creation_event: Optional[FinancialEventModel]) -> bool:
    return (
        creation_event is not None
        and creation_event.origin == "manual"
        and creation_event.ingestion_mode == "live"
    )


def _priority_key(goal: GoalModel) -> tuple[int, int, str]:
    # Current priority_rank (never the target position); an unranked Goal sorts
    # last and the id keeps the order deterministic.
    return (
        1 if goal.priority_rank is None else 0,
        goal.priority_rank if goal.priority_rank is not None else 0,
        str(goal.id),
    )


def _remaining_to_target(
    db_session: Session, goal: GoalModel, user_id: UUID,
) -> Decimal:
    total = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session, goal_id=goal.id, user_id=user_id,
    )

    return max(goal.target_amount - total, ZERO)


# Builds the plan of one rule in Goal priority order: fixed amounts or the
# percentage waterfall, each target limited by its own cap and (cap_at_target)
# by the Goal's remaining target. Only positive cent amounts are planned.
def _build_plan(
    db_session: Session,
    rule_model: FinancialRuleModel,
    targets: list[FinancialRuleGoalTargetModel],
    goals: dict[UUID, GoalModel],
    user_id: UUID,
    income_amount: Decimal,
) -> list[_PlannedItem]:
    ordered = sorted(
        ((target, goals[target.goal_id]) for target in targets),
        key=lambda pair: _priority_key(pair[1]),
    )

    percent_budget: Optional[Decimal] = None

    if rule_model.policy == POLICY_PERCENT:
        # ROUND_DOWN to cents on Income.amount (never base_amount); the
        # unallocated remainder stays on the Account (P44, P45).
        percent_budget = (income_amount * rule_model.percent / Decimal("100")).quantize(
            CENT, rounding=ROUND_DOWN,
        )

    plan: list[_PlannedItem] = []

    for target, goal in ordered:
        if rule_model.policy == POLICY_FIXED:
            wanted = target.amount_or_cap
        else:
            wanted = percent_budget
            if target.amount_or_cap is not None:
                wanted = min(wanted, target.amount_or_cap)

        if rule_model.cap_at_target:
            wanted = min(wanted, _remaining_to_target(db_session, goal, user_id))

        wanted = wanted.quantize(CENT, rounding=ROUND_DOWN)

        if wanted <= ZERO:
            continue

        if percent_budget is not None:
            percent_budget -= wanted

        plan.append(_PlannedItem(goal=goal, position=target.position, planned=wanted))

    return plan


def _blocked_reason(
    account: AccountModel,
    targets: list[FinancialRuleGoalTargetModel],
    goals: dict[UUID, GoalModel],
    income_currency: str,
) -> Optional[str]:
    if account.status == "archived":
        return REASON_SOURCE_ACCOUNT_ARCHIVED

    if any(goals[target.goal_id].status == "archived" for target in targets):
        return REASON_TARGET_GOAL_ARCHIVED

    if account.currency != income_currency or any(
        goals[target.goal_id].currency != account.currency for target in targets
    ):
        return REASON_CURRENCY_MISMATCH

    return None


def _assert_item_matches_transaction(
    item: RuleExecutionItemModel,
    execution: RuleExecutionModel,
    transaction: Any,
) -> None:
    # The item -> GoalTransaction link must agree on owner, execution, Goal,
    # Account and applied amount (the accepted E6 review follow-up).
    if not (
        item.user_id == transaction.user_id == execution.user_id
        and item.execution_id == execution.id == transaction.rule_execution_id
        and item.goal_id == transaction.goal_id
        and item.account_id == transaction.account_id
        and item.applied_amount == transaction.amount
        and item.goal_transaction_id == transaction.id
        and transaction.type == "contribution"
        and transaction.client_request_id is None
    ):
        raise RuleExecutionInvariantError("item and goal transaction disagree")


# Writes ONE GoalTransaction for an execution item and links it (shared by AUTO
# execution and CONFIRM confirmation). The caller holds L0 and the Goal and
# Account locks. The transaction is a contribution linked to the source Account
# with no client_request_id; the item <-> transaction agreement is asserted
# before returning, so a mismatch rolls the whole transaction back.
def write_item_transaction(
    db_session: Session,
    user_id: UUID,
    execution: RuleExecutionModel,
    item_model: RuleExecutionItemModel,
    goal: GoalModel,
    description: str,
    applied: Decimal,
    today: date,
) -> None:
    transaction = goal_transaction_repository.create_transaction(
        db_session=db_session,
        goal_id=goal.id,
        user_id=user_id,
        type="contribution",
        amount=applied,
        description=description[:255],
        currency=goal.currency,
        effective_date=today,
        client_request_id=None,
        account_id=item_model.account_id,
        rule_execution_id=execution.id,
        commit=False,
    )
    item_model.applied_amount = applied
    item_model.goal_transaction_id = transaction.id
    db_session.flush()
    _assert_item_matches_transaction(item_model, execution, transaction)


# Executes one eligible rule inside the already locked transaction and writes
# the execution row, its items, the GoalTransactions and the audit row. The
# capacity object is mutated so later rules of the same event see what this
# rule consumed (the deterministic S31 waterfall).
def _execute_rule(
    db_session: Session,
    user_id: UUID,
    event_model: FinancialEventModel,
    rule_model: FinancialRuleModel,
    targets: list[FinancialRuleGoalTargetModel],
    goals: dict[UUID, GoalModel],
    capacity: _AccountCapacity,
    today: date,
    summary: _OutcomeSummary,
) -> None:
    status: str
    reason_code: Optional[str] = None
    items_to_apply: list[tuple[_PlannedItem, Decimal]] = []
    plan: list[_PlannedItem] = []
    is_confirm = rule_model.execution_mode == MODE_CONFIRM
    proposal_partial = False

    capacity_reservable = capacity.reservable
    capacity_floor = capacity.floor
    capacity_holds = capacity.holds

    blocked = _blocked_reason(capacity.account, targets, goals, event_model.snap_currency)

    if blocked is not None:
        status, reason_code = STATUS_BLOCKED, blocked
    else:
        plan = _build_plan(
            db_session, rule_model, targets, goals, user_id, event_model.snap_amount,
        )
        total = sum((item.planned for item in plan), ZERO)
        available = capacity.rule_capacity

        if not plan:
            status, reason_code = STATUS_SKIPPED, REASON_NOTHING_TO_ALLOCATE
        elif available >= total:
            status = STATUS_AWAITING_CONFIRMATION if is_confirm else STATUS_EXECUTED
            items_to_apply = [(item, item.planned) for item in plan]
        elif rule_model.allow_partial and available > ZERO:
            # Deterministic Goal-priority order until capacity is exhausted.
            status = STATUS_AWAITING_CONFIRMATION if is_confirm else STATUS_EXECUTED_PARTIAL
            proposal_partial = is_confirm
            remaining = available

            for item in plan:
                applied = min(item.planned, remaining)

                if applied > ZERO:
                    items_to_apply.append((item, applied))
                    remaining -= applied
        else:
            status, reason_code = STATUS_SKIPPED, REASON_INSUFFICIENT_CAPACITY

    params_snapshot = _params_snapshot(rule_model, targets)

    if proposal_partial:
        # Remembered so confirmation ends as executed_partial.
        params_snapshot["proposal_partial"] = True

    proposal_fields: dict[str, Any] = {}

    if status == STATUS_AWAITING_CONFIRMATION:
        # hold_sequence is assigned exactly once, here, under L0 (P80); the
        # expiry is immutable (P54). A rollback leaves a harmless gap.
        proposal_fields = {
            "hold_sequence": rule_execution_repository.next_hold_sequence(db_session),
            "expires_at": func.now() + literal_column(PROPOSAL_LIFETIME_SQL),
        }

    execution = rule_execution_repository.add_execution(
        db_session,
        RuleExecutionModel(
            user_id=user_id,
            rule_id=rule_model.id,
            rule_version=rule_model.version,
            params_snapshot=params_snapshot,
            source_type=rule_execution_repository.SOURCE_TYPE_INCOME,
            source_id=event_model.aggregate_id,
            triggering_event_id=event_model.id,
            source_amount=event_model.snap_amount,
            source_currency=event_model.snap_currency,
            source_received_at=event_model.snap_received_at,
            source_account_id=event_model.snap_account_id,
            source_income_source=event_model.snap_income_source,
            capacity_reservable=capacity_reservable,
            capacity_floor=capacity_floor,
            capacity_holds=capacity_holds,
            status=status,
            reason_code=reason_code,
            decided_at=None if status == STATUS_AWAITING_CONFIRMATION else func.now(),
            **proposal_fields,
        ),
    )

    applied_by_goal = {item.goal.id: applied for item, applied in items_to_apply}

    for item in plan:
        if status == STATUS_AWAITING_CONFIRMATION:
            # A proposal's planned amount IS its soft hold, so it holds exactly
            # what a confirmation would write (a partial proposal omits the
            # Goals that do not fit).
            if item.goal.id not in applied_by_goal:
                continue

            planned = applied_by_goal[item.goal.id]
        else:
            planned = item.planned

        item_model = rule_execution_repository.add_item(
            db_session,
            RuleExecutionItemModel(
                user_id=user_id,
                execution_id=execution.id,
                goal_id=item.goal.id,
                account_id=rule_model.source_account_id,
                position=item.position,
                planned_amount=planned,
            ),
        )
        applied = applied_by_goal.get(item.goal.id)

        if applied is None or status == STATUS_AWAITING_CONFIRMATION:
            continue

        write_item_transaction(
            db_session, user_id, execution, item_model, item.goal,
            f"Auto allocation: {rule_model.name}", applied, today,
        )

    applied_total = sum((applied for _, applied in items_to_apply), ZERO)

    if status == STATUS_AWAITING_CONFIRMATION:
        # The new hold reduces what every LATER rule of this event may use,
        # without touching the Account's reservable amount (a hold is not
        # reserved money). The in-memory figure replaces a stale snapshot; the
        # database row is already counted by any later read.
        capacity.holds = capacity.holds + applied_total
    else:
        capacity.reservable = capacity.reservable - applied_total

    audit_code = {
        STATUS_EXECUTED: AUDIT_APPLIED,
        STATUS_EXECUTED_PARTIAL: AUDIT_APPLIED_PARTIAL,
        STATUS_SKIPPED: AUDIT_SKIPPED,
        STATUS_BLOCKED: AUDIT_BLOCKED,
        STATUS_AWAITING_CONFIRMATION: AUDIT_PROPOSED,
    }[status]

    rule_execution_repository.add_audit(
        db_session,
        user_id=user_id,
        execution_id=execution.id,
        code=audit_code,
        related_event_id=event_model.id,
        details={"reason_code": reason_code} if reason_code else None,
    )
    summary.count(status)


def _load_creation_event(
    db_session: Session, user_id: UUID, aggregate_id: UUID,
) -> Optional[FinancialEventModel]:
    return (
        db_session.query(FinancialEventModel)
        .filter(
            FinancialEventModel.user_id == user_id,
            FinancialEventModel.aggregate_id == aggregate_id,
            FinancialEventModel.event_type == EVENT_INCOME_CREATED,
        )
        .first()
    )


# Evaluates every enabled AUTO allocation rule for an income.created event or
# for the first eligibility of an income.updated event, in the approved order,
# inside the caller's transaction (L0 held). Lock order: execution rows, Goals
# ascending id, Accounts ascending id, then the writes (§14.2).
def _evaluate_rules(
    db_session: Session,
    user_id: UUID,
    event_model: FinancialEventModel,
    creation_event: Optional[FinancialEventModel],
    summary: _OutcomeSummary,
) -> None:
    today = financial_event_service.server_today()

    if not _is_live_manual(creation_event):
        summary.not_eligible_for(
            NOT_ELIGIBLE_PROVENANCE if creation_event is not None else NOT_ELIGIBLE_NO_CREATION_EVENT
        )
        return

    rules = rule_execution_repository.get_enabled_allocation_rules(db_session, user_id)

    if not rules:
        return

    existing = rule_execution_repository.get_executions_for_source_for_update(
        db_session, user_id, event_model.aggregate_id,
    )
    targets_by_rule = financial_rule_repository.get_targets_for_rules(
        db_session, user_id, [rule.id for rule in rules],
    )

    eligible: list[FinancialRuleModel] = []

    for rule_model in rules:
        if rule_model.id in existing:
            summary.replayed += 1
            continue

        failure = _eligibility_failure(rule_model, event_model, creation_event)

        if failure is not None:
            summary.not_eligible_for(failure)
            continue

        eligible.append(rule_model)

    if not eligible:
        return

    goal_ids = [
        target.goal_id for rule_model in eligible for target in targets_by_rule.get(rule_model.id, [])
    ]
    goals = rule_execution_repository.get_goals_for_update(db_session, user_id, goal_ids)

    account_ids = {rule_model.source_account_id for rule_model in eligible}
    accounts = account_repository.get_accounts_by_ids_for_update(
        db_session, sorted(account_ids), user_id,
    )
    inputs = account_service.get_rule_capacity_inputs(
        db_session, user_id, list(accounts.values()), today,
    )
    capacities = {
        account_id: _AccountCapacity(
            account=accounts[account_id],
            reservable=inputs[account_id][0],
            floor=inputs[account_id][1],
            holds=inputs[account_id][2],
        )
        for account_id in accounts
    }

    for rule_model in eligible:
        # A rule whose Account or Goal rows are missing is a data-integrity
        # incident (the ownership FKs forbid it), never a business outcome.
        targets = targets_by_rule.get(rule_model.id, [])

        if rule_model.source_account_id not in capacities or any(
            target.goal_id not in goals for target in targets
        ):
            raise RuleExecutionInvariantError("rule references a missing Account or Goal")

        _execute_rule(
            db_session,
            user_id,
            event_model,
            rule_model,
            targets,
            goals,
            capacities[rule_model.source_account_id],
            today,
            summary,
        )


def _annotate_existing(
    db_session: Session,
    user_id: UUID,
    event_model: FinancialEventModel,
    audit_code: str,
    summary: _OutcomeSummary,
) -> dict[UUID, RuleExecutionModel]:
    executions = rule_execution_repository.get_executions_for_source_for_update(
        db_session, user_id, event_model.aggregate_id,
    )

    for execution in executions.values():
        if execution.status == STATUS_AWAITING_CONFIRMATION:
            # An open proposal follows its source (§15.2): EVERY committed
            # income.updated (even a description-only edit) cancels it
            # (source_changed) and every income.deleted cancels it
            # (source_deleted); either ends its hold. Nothing was written, so
            # there is nothing to compensate. Terminal rows are never reached,
            # which makes a redelivered event a no-op. The snapshot comparison
            # applies only to the annotation of COMPLETED executions below.
            if audit_code == AUDIT_SOURCE_DELETED:
                reason = rule_execution_repository.CANCEL_SOURCE_DELETED
            else:
                reason = rule_execution_repository.CANCEL_SOURCE_CHANGED

            rule_execution_repository.cancel_proposal(
                db_session, execution, reason, event_model.id,
            )
            summary.count("cancelled")
            continue

        if rule_execution_repository.audit_exists(
            db_session, user_id, execution.id, audit_code, event_model.id,
        ):
            continue

        if audit_code == AUDIT_SOURCE_CHANGED:
            if execution.status not in (STATUS_EXECUTED, STATUS_EXECUTED_PARTIAL):
                continue

            changed = _changed_fields(
                _execution_snapshot_dict(execution), _snapshot_dict(event_model),
            )

            if not changed:
                continue

            details: Optional[dict[str, Any]] = {"changed_fields": changed}
        else:
            details = None

        rule_execution_repository.add_audit(
            db_session,
            user_id=user_id,
            execution_id=execution.id,
            code=audit_code,
            related_event_id=event_model.id,
            details=details,
        )
        summary.annotated += 1

    return executions


# Processes one claimed event in the caller's transaction. The caller holds
# L0 and the event lock and has verified the claim and the FIFO position.
# Returns:
# - The non-monetary outcome_summary to store on the processed event.
# Raises:
# - EventDeferredError: the business date has not arrived (before any write).
# - Any other exception is a technical failure: the caller rolls back.
def process_event(
    db_session: Session, user_id: UUID, event_model: FinancialEventModel,
) -> dict[str, Any]:
    summary = _OutcomeSummary()

    if (
        event_model.event_type in (EVENT_INCOME_CREATED, EVENT_INCOME_UPDATED)
        and event_model.snap_received_at > financial_event_service.server_today()
    ):
        # The server calendar has not reached the business date yet. Checked
        # before ANY write (including annotations) so a deferral is write-free.
        raise EventDeferredError(
            datetime.combine(event_model.snap_received_at, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=1)
        )

    # Lazy expiry at dispatch (P54): a due proposal is normalized to `expired`
    # before rules are evaluated (its hold already stopped counting).
    rule_execution_repository.expire_due_proposals(db_session, user_id)

    if event_model.event_type == EVENT_INCOME_CREATED:
        _evaluate_rules(db_session, user_id, event_model, event_model, summary)
    elif event_model.event_type == EVENT_INCOME_UPDATED:
        # Existing executions are annotated, never re-run or rewritten; rules
        # without an execution may become eligible, with provenance and the
        # activation limits still measured from the CREATION event.
        _annotate_existing(db_session, user_id, event_model, AUDIT_SOURCE_CHANGED, summary)
        creation_event = _load_creation_event(db_session, user_id, event_model.aggregate_id)
        _evaluate_rules(db_session, user_id, event_model, creation_event, summary)
    elif event_model.event_type == EVENT_INCOME_DELETED:
        # Allocations are preserved: no compensating entries (P47).
        _annotate_existing(db_session, user_id, event_model, AUDIT_SOURCE_DELETED, summary)

    return summary.as_dict(event_model.event_type)


# Lists the caller's executions (newest first) with items and audit, bounded
# by limit/offset. Every read is scoped to the authenticated user.
def list_executions(
    db_session: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    rule_id: Optional[UUID] = None,
    status: Optional[str] = None,
) -> RuleExecutionListResponse:
    executions, total = rule_execution_repository.list_executions(
        db_session, user_id, limit, offset, rule_id=rule_id, status=status,
    )
    ids = [execution.id for execution in executions]
    items = rule_execution_repository.get_items_for_executions(db_session, user_id, ids)
    audit = rule_execution_repository.get_audit_for_executions(db_session, user_id, ids)

    return RuleExecutionListResponse(
        items=[
            RuleExecutionResponse.model_validate(
                {
                    **{
                        name: getattr(execution, name)
                        for name in RuleExecutionResponse.model_fields
                        if name not in ("items", "audit")
                    },
                    "items": items.get(execution.id, []),
                    "audit": audit.get(execution.id, []),
                },
                from_attributes=True,
            )
            for execution in executions
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
