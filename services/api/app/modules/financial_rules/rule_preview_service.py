# Read-only preview of an INCOME_ALLOCATION rule for a sample income.
#
# Guarantees, enforced rather than assumed:
#  * the preview runs in its OWN session and transaction, opened
#    `READ ONLY, ISOLATION LEVEL REPEATABLE READ` before any business query, so
#    PostgreSQL itself rejects every write, DDL and nextval() with an error;
#  * the transaction is always rolled back and the session closed;
#  * no FOR UPDATE, advisory lock, hold sequence, lazy proposal expiry, audit,
#    alert, event or idempotency write is reachable from here;
#  * the decision is the SAME pure function real execution uses
#    (rule_allocation_planner.decide), fed by the same fact loader.
from contextlib import contextmanager
from decimal import Decimal
from typing import Callable, Iterator, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service
from app.modules.accounts.account_errors import AccountNotFoundError
from app.modules.financial_rules import (
    financial_rule_repository,
    rule_allocation_planner,
    rule_execution_repository,
    rule_execution_service,
)
from app.modules.financial_rules.financial_rule_errors import (
    FinancialRulePreviewNotAvailableError,
)
from app.modules.financial_rules.financial_rule_schemas import RULE_TYPE_INCOME_ALLOCATION
from app.modules.financial_rules.rule_execution_service import RuleExecutionInvariantError
from app.modules.financial_rules.rule_preview_schemas import (
    RulePreviewCapacity,
    RulePreviewItem,
    RulePreviewRequest,
    RulePreviewResponse,
    SampleIncomeResponse,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

NOTICES = ["hypothetical_snapshot", "income_not_recorded", "eligibility_not_evaluated"]


# Opens the dedicated read-only snapshot transaction. SET TRANSACTION must be the
# first statement of the transaction, so it is issued before anything else; the
# rollback in `finally` ends the transaction whatever happened.
@contextmanager
def read_only_snapshot_session(
    session_factory: Callable[[], Session] = SessionLocal,
) -> Iterator[Session]:
    db_session = session_factory()

    try:
        db_session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"),
        )

        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


# Previews one rule for a sample income.
# Raises:
# - FinancialRuleNotFoundError: unknown or foreign rule (404).
# - FinancialRulePreviewNotAvailableError: not an INCOME_ALLOCATION rule (409).
def preview_rule(
    user_id: UUID,
    rule_id: UUID,
    request: RulePreviewRequest,
    session_factory: Callable[[], Session] = SessionLocal,
) -> RulePreviewResponse:
    with read_only_snapshot_session(session_factory) as db_session:
        rule_model = financial_rule_repository.get_rule_by_id(db_session, rule_id, user_id)

        if rule_model.rule_type != RULE_TYPE_INCOME_ALLOCATION:
            raise FinancialRulePreviewNotAvailableError()

        # Transaction start time: constant for the whole REPEATABLE READ snapshot.
        computed_at = db_session.execute(text("SELECT now()")).scalar_one()
        today = rule_execution_service.server_today()
        targets = financial_rule_repository.get_targets_for_rules(
            db_session, user_id, [rule_model.id],
        ).get(rule_model.id, [])
        goals = rule_execution_repository.get_goals(
            db_session, user_id, [target.goal_id for target in targets],
        )

        try:
            account = account_repository.get_account_by_id(
                db_session, rule_model.source_account_id, user_id,
            )
        except AccountNotFoundError as error:
            # The ownership FKs forbid this: a data-integrity incident, not a
            # business outcome (same stance as real execution).
            raise RuleExecutionInvariantError("rule references a missing Account") from error

        if any(target.goal_id not in goals for target in targets):
            raise RuleExecutionInvariantError("rule references a missing Goal")

        reservable, floor, holds = account_service.get_rule_capacity_inputs(
            db_session, user_id, [account], today,
        )[account.id]

        sample_amount = _money(request.sample_income.amount)
        # The income is not recorded. Real execution runs after the income is in
        # the ledger, so planning assumes exactly that credit (and reports it).
        reservable_with_sample = reservable + sample_amount
        rule_capacity = reservable_with_sample - floor - holds

        rule_facts, target_facts, goal_facts = rule_execution_service.planner_inputs(
            db_session, rule_model, targets, goals, user_id,
        )
        decision = rule_allocation_planner.decide(
            rule_facts,
            target_facts,
            goal_facts,
            rule_allocation_planner.AccountFacts(
                archived=account.status == "archived",
                currency=account.currency,
                rule_capacity=rule_capacity,
            ),
            sample_amount,
            account.currency,
        )

        selected_by_goal = {line.goal_id: applied for line, applied in decision.selected}
        items = [
            RulePreviewItem(
                goal_id=line.goal_id,
                position=line.position,
                priority_rank=goal_facts[line.goal_id].priority_rank,
                planned_amount=_money(line.planned),
                selected_amount=_money(selected_by_goal.get(line.goal_id, ZERO)),
            )
            for line in decision.plan
        ]
        planned_total = sum((item.planned_amount for item in items), ZERO)
        selected_total = sum((item.selected_amount for item in items), ZERO)

        if decision.status == rule_allocation_planner.STATUS_BLOCKED:
            outcome, effect = "blocked", "none"
        elif decision.status == rule_allocation_planner.STATUS_SKIPPED:
            outcome, effect = "skipped", "none"
        else:
            is_partial = (
                decision.status == rule_allocation_planner.STATUS_EXECUTED_PARTIAL
                or decision.proposal_partial
            )
            outcome = "partial" if is_partial else "full"
            effect = (
                "would_hold"
                if decision.status == rule_allocation_planner.STATUS_AWAITING_CONFIRMATION
                else "would_apply"
            )

        source: Optional[str] = request.sample_income.source

        return RulePreviewResponse(
            rule_id=rule_model.id,
            rule_version=rule_model.version,
            rule_status=rule_model.status,
            execution_mode=rule_model.execution_mode,
            policy=rule_model.policy,
            as_of_date=today,
            computed_at=computed_at,
            sample_income=SampleIncomeResponse(
                amount=sample_amount,
                currency=account.currency,
                source=source,
                source_selected_by_rule=(
                    None if source is None else source in (rule_model.income_sources or [])
                ),
            ),
            capacity=RulePreviewCapacity(
                account_id=account.id,
                currency=account.currency,
                reservable_amount=_money(reservable),
                assumed_sample_income_credit=sample_amount,
                reservable_with_sample_income=_money(reservable_with_sample),
                minimum_unallocated_floor=_money(floor),
                active_rule_holds=_money(holds),
                rule_capacity=_money(rule_capacity),
            ),
            predicted_outcome=outcome,
            effect=effect,
            reason_code=decision.reason_code,
            items=items,
            planned_total=_money(planned_total),
            selected_total=_money(selected_total),
            notices=list(NOTICES),
        )
