from decimal import Decimal
from uuid import UUID

from app.modules.financial_rules import rule_allocation_planner as planner

D = Decimal
G1, G2, G3 = (UUID(int=1), UUID(int=2), UUID(int=3))


def goal(goal_id: UUID, rank=None, status="active", currency="EUR", remaining="1000.00") -> planner.GoalFacts:
    return planner.GoalFacts(goal_id, rank, status, currency, D(remaining) if remaining is not None else None)


def rule(policy=planner.POLICY_FIXED, percent=None, cap=True, partial=False, confirm=False) -> planner.RuleFacts:
    return planner.RuleFacts(policy, percent, cap, partial, confirm)


def account(capacity="1000.00", archived=False, currency="EUR") -> planner.AccountFacts:
    return planner.AccountFacts(archived, currency, D(capacity))


def targets(*pairs):
    return [planner.TargetFacts(goal_id, index, D(amount) if amount else None) for index, (goal_id, amount) in enumerate(pairs)]


def test_pure_module_has_no_database_or_clock_dependency() -> None:
    source = open(planner.__file__, encoding="utf-8").read()

    for forbidden in ("sqlalchemy", "Session", "datetime", "date.today", "import app."):
        assert forbidden not in source, forbidden


def test_fixed_full_in_priority_order_not_target_position() -> None:
    decision = planner.decide(
        rule(), targets((G1, "100.00"), (G2, "200.00")),
        {G1: goal(G1, rank=2), G2: goal(G2, rank=1)}, account(), D("50.00"), "EUR",
    )

    assert decision.status == planner.STATUS_EXECUTED
    assert [line.goal_id for line in decision.plan] == [G2, G1]  # rank 1 first
    assert [applied for _, applied in decision.selected] == [D("200.00"), D("100.00")]


def test_unranked_goals_sort_last_with_id_tiebreak() -> None:
    decision = planner.decide(
        rule(), targets((G1, "10.00"), (G2, "10.00"), (G3, "10.00")),
        {G1: goal(G1), G2: goal(G2, rank=5), G3: goal(G3)}, account(), D("1.00"), "EUR",
    )

    assert [line.goal_id for line in decision.plan] == [G2, G1, G3]


def test_percent_waterfall_rounds_down_and_respects_target_caps() -> None:
    decision = planner.decide(
        rule(planner.POLICY_PERCENT, D("20.00")), targets((G1, "300.00"), (G2, "200.00"), (G3, None)),
        {G1: goal(G1, 1), G2: goal(G2, 2), G3: goal(G3, 3)}, account(), D("3000.00"), "EUR",
    )

    assert [line.planned for line in decision.plan] == [D("300.00"), D("200.00"), D("100.00")]
    odd = planner.decide(
        rule(planner.POLICY_PERCENT, D("33.33")), targets((G1, None)),
        {G1: goal(G1, 1)}, account(), D("10.00"), "EUR",
    )

    assert odd.plan[0].planned == D("3.33")  # 3.333 rounded DOWN, never to 3.34


def test_cap_at_target_limits_and_removes_reached_goals() -> None:
    decision = planner.decide(
        rule(), targets((G1, "300.00"), (G2, "300.00")),
        {G1: goal(G1, 1, remaining="50.00"), G2: goal(G2, 2, remaining="0.00")}, account(), D("1.00"), "EUR",
    )

    assert [(line.goal_id, line.planned) for line in decision.plan] == [(G1, D("50.00"))]
    uncapped = planner.decide(
        rule(cap=False), targets((G1, "300.00")), {G1: goal(G1, 1, remaining=None)}, account(), D("1.00"), "EUR",
    )

    assert uncapped.plan[0].planned == D("300.00")


def test_partial_waterfall_and_proposal_partial_flag() -> None:
    args = (targets((G1, "150.00"), (G2, "100.00")), {G1: goal(G1, 1), G2: goal(G2, 2)}, account("200.00"), D("1.00"), "EUR")
    auto = planner.decide(rule(partial=True), *args)
    confirm = planner.decide(rule(partial=True, confirm=True), *args)

    assert auto.status == planner.STATUS_EXECUTED_PARTIAL and not auto.proposal_partial
    assert [(line.goal_id, applied) for line, applied in auto.selected] == [(G1, D("150.00")), (G2, D("50.00"))]
    assert confirm.status == planner.STATUS_AWAITING_CONFIRMATION and confirm.proposal_partial


def test_insufficient_nothing_and_zero_capacity_outcomes() -> None:
    base = (targets((G1, "150.00")), {G1: goal(G1, 1)})
    strict = planner.decide(rule(), *base, account("100.00"), D("1.00"), "EUR")
    zero_partial = planner.decide(rule(partial=True), *base, account("0.00"), D("1.00"), "EUR")
    nothing = planner.decide(
        rule(planner.POLICY_PERCENT, D("0.01")), *base, account(), D("1.00"), "EUR",
    )

    assert (strict.status, strict.reason_code, len(strict.plan), strict.selected) == (
        planner.STATUS_SKIPPED, planner.REASON_INSUFFICIENT_CAPACITY, 1, (),
    )
    assert zero_partial.reason_code == planner.REASON_INSUFFICIENT_CAPACITY
    assert (nothing.status, nothing.reason_code, nothing.plan) == (
        planner.STATUS_SKIPPED, planner.REASON_NOTHING_TO_ALLOCATE, (),
    )


def test_blocked_reasons_and_their_precedence() -> None:
    base = (targets((G1, "10.00")),)

    assert planner.decide(rule(), *base, {G1: goal(G1, status="archived")}, account(archived=True), D("1.00"), "EUR").reason_code == (
        planner.REASON_SOURCE_ACCOUNT_ARCHIVED
    )
    assert planner.decide(rule(), *base, {G1: goal(G1, status="archived")}, account(), D("1.00"), "EUR").reason_code == (
        planner.REASON_TARGET_GOAL_ARCHIVED
    )
    assert planner.decide(rule(), *base, {G1: goal(G1, currency="USD")}, account(), D("1.00"), "EUR").reason_code == (
        planner.REASON_CURRENCY_MISMATCH
    )
    assert planner.decide(rule(), *base, {G1: goal(G1)}, account(), D("1.00"), "USD").reason_code == (
        planner.REASON_CURRENCY_MISMATCH
    )
    blocked = planner.decide(rule(), *base, {G1: goal(G1, currency="USD")}, account(), D("1.00"), "EUR")

    assert blocked.status == planner.STATUS_BLOCKED and blocked.plan == () and blocked.selected == ()
