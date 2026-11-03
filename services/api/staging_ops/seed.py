"""
Staging seed through the backend domain services.

What:
    Creates the synthetic scenarios of seed_scenarios.py for the two QA
    actors on a verified staging database, using the same services the API
    uses, so every ledger invariant, ownership rule and domain event applies.

Why:
    Direct ledger inserts would bypass the invariants the product depends on.
    The seed is repeat-safe: an actor that already holds the completion marker
    (an Account named QA-SEED-<staging id>, created last) is left untouched,
    and an actor with data but no marker is refused instead of topped up, so a
    second run can never duplicate a financial effect. Recovery from a
    half-seeded actor is the explicit reset procedure.
"""

from datetime import date
from typing import Callable, Dict, List, Mapping, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from staging_ops.bootstrap import verify_target
from staging_ops.errors import StagingRefused, unexpected
from staging_ops.evidence import EvidenceRecord, utc_now, write_evidence
from staging_ops.identity import assert_same_identity
from staging_ops.operations import Operations
from staging_ops.seed_scenarios import ACTORS, BASE_CURRENCY, MINIMUM_ROWS, build_scenarios, marker_name
from staging_ops.target_config import ApprovedTargets

# Tables whose rows for a user mean "this actor already has data".
_OWNED_TABLES = ("accounts", "goals", "budgets", "income", "expenses", "financial_rules")
_COUNTED_TABLES = _OWNED_TABLES + ("rule_executions", "rule_alerts", "goal_transactions")


# Validates the actor-to-user mapping the operator supplies.
# The Supabase Auth users are created by the owner in the staging project;
# this tool never creates Auth users or invents identifiers.
# Parameters:
# - mapping: {"QA-A": "<uuid>", "QA-B": "<uuid>"}.
# Returns:
# - {actor: UUID}
# Raises:
# - StagingRefused: USERS_INVALID unless both actors map to distinct UUIDs.
def parse_users(mapping: Mapping[str, str]) -> Dict[str, UUID]:
    try:
        if set(mapping) != set(ACTORS):
            raise ValueError
        users = {actor: UUID(str(mapping[actor])) for actor in ACTORS}
    except (ValueError, TypeError, AttributeError):
        raise StagingRefused("USERS_INVALID", "the users file must map exactly QA-A and QA-B to UUIDs") from None

    if len(set(users.values())) != len(users):
        raise StagingRefused("USERS_INVALID", "QA-A and QA-B must be different users")

    return users


def _resolve(value, ids: Mapping[str, UUID]):
    if isinstance(value, str) and value.startswith("$ref:"):
        return str(ids[value[len("$ref:"):]])

    if isinstance(value, list):
        return [_resolve(item, ids) for item in value]

    if isinstance(value, dict):
        return {name: _resolve(item, ids) for name, item in value.items()}

    return value


def _count(session: Session, table: str, user_id: UUID) -> int:
    # The table name comes from the fixed tuples above, never from input.
    return int(session.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :user_id"), {"user_id": user_id}).scalar())


def _run_step(session: Session, step, user_id: UUID, ids: Dict[str, UUID]) -> Optional[UUID]:
    from app.modules.accounts import account_service
    from app.modules.accounts.account_schemas import AccountCreate
    from app.modules.budgets import budget_service
    from app.modules.budgets.budget_schemas import BudgetCreate
    from app.modules.categories import service as category_service
    from app.modules.categories.schemas import CategoryCreate
    from app.modules.expenses import expenses_service
    from app.modules.expenses.expenses_schemas import ExpenseCreate
    from app.modules.financial_events import financial_event_processor
    from app.modules.financial_rules import financial_rule_service, rule_alert_service
    from app.modules.financial_rules.financial_rule_schemas import financial_rule_create_adapter
    from app.modules.goals import goal_service
    from app.modules.goals.goal_schemas import GoalCreate
    from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate
    from app.modules.income import income_service
    from app.modules.income.income_schemas import IncomeCreate

    payload = _resolve(step.payload, ids)
    kind = step.kind

    if kind == "category":
        return category_service.create_category(session, CategoryCreate.model_validate(payload), user_id).id

    if kind == "account":
        return account_service.create_account(session, AccountCreate.model_validate(payload), user_id).id

    if kind == "goal":
        return goal_service.create_goal(session, GoalCreate.model_validate(payload), user_id).id

    if kind == "budget":
        return budget_service.create_budget(session, BudgetCreate.model_validate(payload), user_id).id

    if kind == "rule":
        rule = financial_rule_service.create_rule(session, financial_rule_create_adapter.validate_python(payload), user_id)
        financial_rule_service.enable_rule(session, rule.id, user_id)
        return rule.id

    if kind == "income":
        return income_service.create_income(session, IncomeCreate.model_validate(payload), user_id).id

    if kind == "expense":
        return expenses_service.create_expense(session, ExpenseCreate.model_validate(payload), user_id).id

    if kind == "reservation":
        goal_id = ids[payload.pop("goal")]
        result = goal_service.create_or_replay_goal_transaction(session, goal_id, GoalTransactionCreate.model_validate(payload), user_id)
        return result.transaction.id

    if kind == "drain":
        summary = financial_event_processor.drain_user_events(session, user_id)

        if summary.failed_retryable or summary.dead or summary.unrecorded_failures or summary.blocked:
            raise StagingRefused("SEED_DRAIN_FAILED", "the rule event drain did not complete cleanly")

        return None

    if kind == "alerts":
        rule_alert_service.evaluate_user_alerts(session, user_id)

        return None

    raise StagingRefused("SEED_STEP_UNKNOWN", "unknown seed step kind")


def _seed_actor(
    session: Session,
    actor: str,
    user_id: UUID,
    staging_id: str,
    steps,
    record: EvidenceRecord,
) -> Optional[Dict[str, List[dict]]]:
    marker = marker_name(staging_id)
    has_marker = session.execute(
        text("SELECT count(*) FROM accounts WHERE user_id = :user_id AND name = :name"), {"user_id": user_id, "name": marker},
    ).scalar()
    session.rollback()

    if has_marker:
        record.step(f"{actor}-already-seeded-no-change")
        return None

    if any(_count(session, table, user_id) for table in _OWNED_TABLES):
        session.rollback()
        raise StagingRefused("ACTOR_HAS_DATA", f"{actor} already has data but no completion marker; run the reset procedure instead of seeding on top")

    session.rollback()

    from app.modules.financial_settings import financial_settings_service

    if financial_settings_service.get_base_currency(session, user_id) != BASE_CURRENCY:
        raise StagingRefused("BASE_CURRENCY_UNEXPECTED", "the seed requires the base currency EUR so it needs no exchange-rate lookup")

    ids: Dict[str, UUID] = {}
    manifest: Dict[str, List[dict]] = {}

    for step in steps:
        entity_id = _run_step(session, step, user_id, ids)

        if entity_id is not None:
            ids[step.key] = entity_id
            manifest.setdefault(step.scenario, []).append({"kind": step.kind, "key": step.key, "id": str(entity_id)})

    # Verified before the marker exists, so a failed check leaves no marker.
    counts = {table: _count(session, table, user_id) for table in _COUNTED_TABLES}
    session.rollback()

    short = [table for table, minimum in MINIMUM_ROWS[actor].items() if counts[table] < minimum]

    if short:
        raise StagingRefused("SEED_VERIFICATION_FAILED", f"{actor} scenarios did not produce the expected rows in: {', '.join(short)}")

    from app.modules.accounts import account_service
    from app.modules.accounts.account_schemas import AccountCreate

    account_service.create_account(session, AccountCreate.model_validate({"name": marker, "type": "cash", "currency": BASE_CURRENCY}), user_id)
    record.details[f"{actor}_rows"] = counts
    record.step(f"{actor}-seeded")

    return manifest


# Verifies, in SQL, that no seeded object references another user's data.
def _verify_isolation(session: Session) -> None:
    mismatches = session.execute(text(
        "SELECT (SELECT count(*) FROM goal_transactions t JOIN goals g ON g.id = t.goal_id WHERE t.user_id <> g.user_id)"
        " + (SELECT count(*) FROM financial_rules r JOIN accounts a ON a.id = r.source_account_id WHERE r.user_id <> a.user_id)"
        " + (SELECT count(*) FROM budgets b JOIN categories c ON c.id = b.category_id WHERE b.user_id <> c.user_id)"
    )).scalar()
    session.rollback()

    if mismatches:
        raise StagingRefused("SEED_ISOLATION_BROKEN", "a seeded object references another user's data")


# Staging seed entry point.
# Parameters:
# - users: operator-supplied {actor: Auth user id}; never invented here.
# - as_of: business date the scenarios derive from.
# - other parameters: as for bootstrap().
# Returns:
# - The EvidenceRecord (outcome OK); the manifest of created ids is in details.
# Raises:
# - StagingRefused: before any write unless the target is the verified one.
def seed(
    environment_flag: Optional[str],
    staging_id: Optional[str],
    environ: Mapping[str, str],
    approved: ApprovedTargets,
    operations: Operations,
    users: Mapping[str, str],
    as_of: date,
    evidence_dir: Optional[str] = None,
    say: Callable[[str], None] = print,
    clock=None,
) -> EvidenceRecord:
    record = EvidenceRecord(operation="seed", started_at=utc_now(clock))

    try:
        configured, verified, _facts = verify_target(environment_flag, staging_id, environ, approved, operations, record)
        user_ids = parse_users(users)
        record.step("users-mapping-valid")

        if operations.open_session is None:
            raise StagingRefused("SEED_UNAVAILABLE", "no database session factory is configured")

        assert_same_identity(verified, operations.probe(configured))
        record.step("identity-unchanged-before-seed")

        scenarios = build_scenarios(as_of)
        record.outcome = "FAILED"  # from here a stop may leave a partly seeded actor
        session = operations.open_session(verified)

        try:
            manifest = {}

            for actor in ACTORS:
                created = _seed_actor(session, actor, user_ids[actor], configured.staging_id, scenarios[actor], record)

                if created is not None:
                    manifest[actor] = created

            _verify_isolation(session)
            record.step("cross-user-isolation-verified")
        finally:
            session.close()

        record.details["as_of"] = as_of.isoformat()
        record.details["manifest"] = manifest
        record.outcome = "OK"
    except StagingRefused as error:
        record.code = error.code
        error.mutated = record.outcome == "FAILED"
        raise
    except Exception as error:
        failure = unexpected(error)
        record.code = failure.code
        record.details["error_type"] = type(error).__name__
        failure.mutated = record.outcome == "FAILED"
        raise failure from None
    finally:
        record.finished_at = utc_now(clock)

        if evidence_dir:
            write_evidence(evidence_dir, record)

    return record
