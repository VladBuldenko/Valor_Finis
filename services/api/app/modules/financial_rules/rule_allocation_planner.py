# The ONE allocation decision of an INCOME_ALLOCATION rule, as a pure function.
#
# It has no database, session or clock dependency: every fact it needs is passed
# in. Real execution (rule_execution_service._execute_rule) and the read-only
# preview (rule_preview_service) both call `decide`, so a preview can never
# disagree with an execution on identical financial state because of a second,
# independently maintained algorithm.
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional
from uuid import UUID

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

STATUS_EXECUTED = "executed"
STATUS_EXECUTED_PARTIAL = "executed_partial"
STATUS_SKIPPED = "skipped"
STATUS_BLOCKED = "blocked"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"

REASON_INSUFFICIENT_CAPACITY = "insufficient_capacity"
REASON_NOTHING_TO_ALLOCATE = "nothing_to_allocate"
REASON_SOURCE_ACCOUNT_ARCHIVED = "source_account_archived"
REASON_TARGET_GOAL_ARCHIVED = "target_goal_archived"
REASON_CURRENCY_MISMATCH = "currency_mismatch"

MODE_AUTO = "AUTO"
MODE_CONFIRM = "CONFIRM"

POLICY_FIXED = "FIXED_PER_GOAL"
POLICY_PERCENT = "PERCENT_OF_INCOME_WATERFALL"


@dataclass(frozen=True)
class GoalFacts:
    id: UUID
    priority_rank: Optional[int]
    status: str
    currency: str
    # Remaining distance to the Goal's target (never negative). Only read when the
    # rule has cap_at_target; the caller may pass None otherwise.
    remaining_to_target: Optional[Decimal]


@dataclass(frozen=True)
class TargetFacts:
    goal_id: UUID
    position: int
    amount_or_cap: Optional[Decimal]


@dataclass(frozen=True)
class RuleFacts:
    policy: str
    percent: Optional[Decimal]
    cap_at_target: bool
    allow_partial: bool
    is_confirm: bool


@dataclass(frozen=True)
class AccountFacts:
    archived: bool
    currency: str
    # reservable - floor - active holds (the rule's capacity), already computed.
    rule_capacity: Decimal


@dataclass(frozen=True)
class PlannedLine:
    goal_id: UUID
    position: int
    planned: Decimal


@dataclass(frozen=True)
class AllocationDecision:
    status: str
    reason_code: Optional[str]
    # The wanted plan in Goal priority order (empty when blocked).
    plan: tuple[PlannedLine, ...]
    # What would actually be applied (or held, for a CONFIRM proposal).
    selected: tuple[tuple[PlannedLine, Decimal], ...]
    # A CONFIRM proposal that holds less than the plan (confirmation then ends
    # as executed_partial).
    proposal_partial: bool


def _priority_key(goal: GoalFacts) -> tuple[int, int, str]:
    # Current priority_rank (never the target position); an unranked Goal sorts
    # last and the id keeps the order deterministic.
    return (
        1 if goal.priority_rank is None else 0,
        goal.priority_rank if goal.priority_rank is not None else 0,
        str(goal.id),
    )


def blocked_reason(
    account: AccountFacts,
    targets: list[TargetFacts],
    goals: dict[UUID, GoalFacts],
    income_currency: str,
) -> Optional[str]:
    if account.archived:
        return REASON_SOURCE_ACCOUNT_ARCHIVED

    if any(goals[target.goal_id].status == "archived" for target in targets):
        return REASON_TARGET_GOAL_ARCHIVED

    if account.currency != income_currency or any(
        goals[target.goal_id].currency != account.currency for target in targets
    ):
        return REASON_CURRENCY_MISMATCH

    return None


# The plan of one rule in Goal priority order: fixed amounts or the percentage
# waterfall, each target limited by its own cap and (cap_at_target) by the Goal's
# remaining target. Only positive cent amounts are planned.
def build_plan(
    rule: RuleFacts,
    targets: list[TargetFacts],
    goals: dict[UUID, GoalFacts],
    income_amount: Decimal,
) -> list[PlannedLine]:
    ordered = sorted(
        ((target, goals[target.goal_id]) for target in targets),
        key=lambda pair: _priority_key(pair[1]),
    )

    percent_budget: Optional[Decimal] = None

    if rule.policy == POLICY_PERCENT:
        # ROUND_DOWN to cents on Income.amount (never base_amount); the
        # unallocated remainder stays on the Account (P44, P45).
        percent_budget = (income_amount * rule.percent / Decimal("100")).quantize(
            CENT, rounding=ROUND_DOWN,
        )

    plan: list[PlannedLine] = []

    for target, goal in ordered:
        if rule.policy == POLICY_FIXED:
            wanted = target.amount_or_cap
        else:
            wanted = percent_budget
            if target.amount_or_cap is not None:
                wanted = min(wanted, target.amount_or_cap)

        if rule.cap_at_target:
            wanted = min(wanted, goal.remaining_to_target)

        wanted = wanted.quantize(CENT, rounding=ROUND_DOWN)

        if wanted <= ZERO:
            continue

        if percent_budget is not None:
            percent_budget -= wanted

        plan.append(PlannedLine(goal_id=goal.id, position=target.position, planned=wanted))

    return plan


# Decides the outcome of one rule for one income amount against the given
# capacity. No side effects.
def decide(
    rule: RuleFacts,
    targets: list[TargetFacts],
    goals: dict[UUID, GoalFacts],
    account: AccountFacts,
    income_amount: Decimal,
    income_currency: str,
) -> AllocationDecision:
    blocked = blocked_reason(account, targets, goals, income_currency)

    if blocked is not None:
        return AllocationDecision(STATUS_BLOCKED, blocked, (), (), False)

    plan = build_plan(rule, targets, goals, income_amount)
    total = sum((line.planned for line in plan), ZERO)
    available = account.rule_capacity

    if not plan:
        return AllocationDecision(STATUS_SKIPPED, REASON_NOTHING_TO_ALLOCATE, (), (), False)

    if available >= total:
        status = STATUS_AWAITING_CONFIRMATION if rule.is_confirm else STATUS_EXECUTED

        return AllocationDecision(
            status, None, tuple(plan), tuple((line, line.planned) for line in plan), False,
        )

    if rule.allow_partial and available > ZERO:
        # Deterministic Goal-priority order until capacity is exhausted.
        selected: list[tuple[PlannedLine, Decimal]] = []
        remaining = available

        for line in plan:
            applied = min(line.planned, remaining)

            if applied > ZERO:
                selected.append((line, applied))
                remaining -= applied

        status = STATUS_AWAITING_CONFIRMATION if rule.is_confirm else STATUS_EXECUTED_PARTIAL

        return AllocationDecision(status, None, tuple(plan), tuple(selected), rule.is_confirm)

    return AllocationDecision(STATUS_SKIPPED, REASON_INSUFFICIENT_CAPACITY, tuple(plan), (), False)
