from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts import account_repository
from app.modules.accounts.account_models import AccountModel
from app.modules.budgets import budget_repository
from app.modules.financial_rules import (
    financial_rule_repository,
    rule_alert_repository,
    rule_execution_repository,
)
from app.modules.financial_rules.financial_rule_errors import (
    FinancialRuleActivationNotAvailableError,
    FinancialRuleAlreadyExistsError,
    FinancialRuleCurrencyMismatchError,
    FinancialRuleDeletionNotAllowedError,
    FinancialRuleInvalidFieldsError,
    FinancialRuleInvalidTransitionError,
    FinancialRuleSubjectArchivedError,
)
from app.modules.financial_rules.financial_rule_models import (
    FinancialRuleGoalTargetModel,
    FinancialRuleModel,
)
from app.modules.financial_rules.financial_rule_schemas import (
    RULE_TYPE_BUDGET_ALERT,
    RULE_TYPE_FLOOR,
    RULE_TYPE_INCOME_ALLOCATION,
    RULE_TYPE_OVERCOMMITMENT,
    BudgetAlertRuleResponse,
    FinancialRuleCreate,
    FinancialRuleGoalTargetInput,
    FinancialRuleGoalTargetResponse,
    FinancialRuleUpdate,
    FloorRuleResponse,
    IncomeAllocationRuleResponse,
    OvercommitmentAlertRuleResponse,
    financial_rule_create_adapter,
)
from app.modules.goals import goal_repository, goal_user_lock

# Rules CRUD and the safety-floor runtime (VF-020E5).
#
# Transaction ownership: every service function owns ONE transaction. Every
# WRITE takes the user advisory lock L0 first (the VF-020D primitive), then
# the rule row, then the referenced Account / Budget row FOR UPDATE; Goal
# writes also take L0, so rule writes and Goal lifecycle writes serialize.
# No network call happens under these locks. Nothing here executes a rule,
# creates a money row, or reads executions, holds, alerts or events.

# Fields a PATCH may carry per rule type.
ALLOWED_UPDATE_FIELDS: dict[str, frozenset[str]] = {
    RULE_TYPE_INCOME_ALLOCATION: frozenset({
        "name", "description", "source_account_id", "execution_mode", "execution_order",
        "effective_from", "policy", "percent", "cap_at_target", "allow_partial",
        "income_sources", "targets",
    }),
    RULE_TYPE_FLOOR: frozenset({"name", "description", "source_account_id", "floor_amount"}),
    RULE_TYPE_OVERCOMMITMENT: frozenset({"name", "description", "source_account_id"}),
    RULE_TYPE_BUDGET_ALERT: frozenset({"name", "description", "budget_id"}),
}

# Fields that may be explicitly null in a PATCH; any other explicit null is
# an invalid request.
NULLABLE_UPDATE_FIELDS = frozenset({"description", "effective_from", "percent"})

# Fields whose change is a MATERIAL edit (version + 1). name, description,
# execution_order and target positions are non-material.
MATERIAL_SCALAR_FIELDS: dict[str, tuple[str, ...]] = {
    RULE_TYPE_INCOME_ALLOCATION: (
        "execution_mode", "source_account_id", "policy", "percent", "cap_at_target",
        "allow_partial", "effective_from",
    ),
    RULE_TYPE_FLOOR: ("source_account_id", "floor_amount"),
    RULE_TYPE_OVERCOMMITMENT: ("source_account_id",),
    RULE_TYPE_BUDGET_ALERT: ("budget_id",),
}

UNIQUE_CONSTRAINT_NAMES = frozenset({
    "uq_financial_rules_floor_user_id_source_account_id",
    "uq_financial_rules_overcommitment_user_id_source_account_id",
    "uq_financial_rules_budget_alert_user_id_budget_id",
})


def _constraint_name(error: IntegrityError) -> Optional[str]:
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _translate_integrity_error(error: IntegrityError) -> Exception:
    name = _constraint_name(error)

    if name in UNIQUE_CONSTRAINT_NAMES:
        return FinancialRuleAlreadyExistsError()

    return error


def _build_response(
    rule_model: FinancialRuleModel,
    target_models: list[FinancialRuleGoalTargetModel],
):
    common: dict[str, Any] = dict(
        id=rule_model.id,
        user_id=rule_model.user_id,
        name=rule_model.name,
        description=rule_model.description,
        status=rule_model.status,
        version=rule_model.version,
        active_since=rule_model.active_since,
        created_at=rule_model.created_at,
        updated_at=rule_model.updated_at,
    )

    if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
        return IncomeAllocationRuleResponse(
            rule_type=RULE_TYPE_INCOME_ALLOCATION,
            source_account_id=rule_model.source_account_id,
            execution_mode=rule_model.execution_mode,
            execution_order=rule_model.execution_order,
            effective_from=rule_model.effective_from,
            policy=rule_model.policy,
            percent=rule_model.percent,
            cap_at_target=rule_model.cap_at_target,
            allow_partial=rule_model.allow_partial,
            income_sources=list(rule_model.income_sources or []),
            targets=[
                FinancialRuleGoalTargetResponse.model_validate(target)
                for target in target_models
            ],
            **common,
        )

    if rule_model.rule_type == RULE_TYPE_FLOOR:
        return FloorRuleResponse(
            rule_type=RULE_TYPE_FLOOR,
            source_account_id=rule_model.source_account_id,
            floor_amount=rule_model.floor_amount,
            **common,
        )

    if rule_model.rule_type == RULE_TYPE_OVERCOMMITMENT:
        return OvercommitmentAlertRuleResponse(
            rule_type=RULE_TYPE_OVERCOMMITMENT,
            source_account_id=rule_model.source_account_id,
            **common,
        )

    return BudgetAlertRuleResponse(
        rule_type=RULE_TYPE_BUDGET_ALERT,
        budget_id=rule_model.budget_id,
        **common,
    )


def _respond(db_session: Session, rule_model: FinancialRuleModel):
    targets = financial_rule_repository.get_targets_for_rules(
        db_session, rule_model.user_id, [rule_model.id],
    ).get(rule_model.id, [])

    return _build_response(rule_model, targets)


# ------------------------------------------------------------------
# Reference validation (before relying on a foreign key failure)
# ------------------------------------------------------------------


# Validates an allocation rule's source Account and target Goals and returns
# the locked Account. Missing / foreign -> 404 (existing not-found errors);
# archived Account or Goal -> 409; currency mismatch -> 422. Completed Goals
# are valid targets (P11).
def _validate_allocation_references(
    db_session: Session,
    user_id: UUID,
    source_account_id: UUID,
    goal_ids_to_check: list[UUID],
    check_account_status: bool,
) -> AccountModel:
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session, account_id=source_account_id, user_id=user_id,
    )

    if check_account_status and account_model.status == "archived":
        raise FinancialRuleSubjectArchivedError()

    goal_models = [
        goal_repository.get_goal_by_id(db_session=db_session, goal_id=goal_id, user_id=user_id)
        for goal_id in goal_ids_to_check
    ]

    if any(goal.status == "archived" for goal in goal_models):
        raise FinancialRuleSubjectArchivedError()

    if any(goal.currency != account_model.currency for goal in goal_models):
        raise FinancialRuleCurrencyMismatchError()

    return account_model


def _lock_account(db_session: Session, user_id: UUID, account_id: UUID) -> AccountModel:
    return account_repository.get_account_by_id_for_update(
        db_session=db_session, account_id=account_id, user_id=user_id,
    )


def _assert_subject_unique(
    db_session: Session,
    user_id: UUID,
    rule_type: str,
    source_account_id: Optional[UUID],
    budget_id: Optional[UUID],
    exclude_rule_id: Optional[UUID] = None,
) -> None:
    if financial_rule_repository.subject_rule_exists(
        db_session, user_id, rule_type, source_account_id, budget_id, exclude_rule_id,
    ):
        raise FinancialRuleAlreadyExistsError()


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------


def _target_models_from_inputs(
    rule_id: UUID, user_id: UUID, targets: list[FinancialRuleGoalTargetInput],
) -> list[FinancialRuleGoalTargetModel]:
    return [
        FinancialRuleGoalTargetModel(
            id=uuid4(),
            rule_id=rule_id,
            user_id=user_id,
            goal_id=target.goal_id,
            amount_or_cap=target.amount_or_cap,
            position=target.position if target.position is not None else index,
        )
        for index, target in enumerate(targets)
    ]


# Creates a rule as a draft with version 1. The whole operation is one
# transaction that starts with the user lock L0.
# Raises: Account / Goal / Budget not-found errors (404), subject-archived and
# already-exists errors (409), currency mismatch (422).
def create_rule(db_session: Session, rule_data: FinancialRuleCreate, user_id: UUID):
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        rule_model = FinancialRuleModel(
            id=uuid4(),
            user_id=user_id,
            name=rule_data.name,
            description=rule_data.description,
            rule_type=rule_data.rule_type,
        )
        target_inputs: list[FinancialRuleGoalTargetInput] = []

        if rule_data.rule_type == RULE_TYPE_INCOME_ALLOCATION:
            _validate_allocation_references(
                db_session, user_id, rule_data.source_account_id,
                [target.goal_id for target in rule_data.targets], check_account_status=True,
            )
            rule_model.source_account_id = rule_data.source_account_id
            rule_model.execution_mode = rule_data.execution_mode
            rule_model.execution_order = (
                rule_data.execution_order
                if rule_data.execution_order is not None
                else financial_rule_repository.get_next_execution_order(db_session, user_id)
            )
            rule_model.effective_from = rule_data.effective_from
            rule_model.policy = rule_data.policy
            rule_model.percent = rule_data.percent
            rule_model.cap_at_target = rule_data.cap_at_target
            rule_model.allow_partial = rule_data.allow_partial
            rule_model.income_sources = list(rule_data.income_sources)
            target_inputs = rule_data.targets
        elif rule_data.rule_type == RULE_TYPE_BUDGET_ALERT:
            budget_repository.get_budget_by_id_for_update(
                db_session=db_session, budget_id=rule_data.budget_id, user_id=user_id,
            )
            _assert_subject_unique(db_session, user_id, rule_data.rule_type, None, rule_data.budget_id)
            rule_model.budget_id = rule_data.budget_id
        else:
            _lock_account(db_session, user_id, rule_data.source_account_id)
            _assert_subject_unique(
                db_session, user_id, rule_data.rule_type, rule_data.source_account_id, None,
            )
            rule_model.source_account_id = rule_data.source_account_id

            if rule_data.rule_type == RULE_TYPE_FLOOR:
                rule_model.floor_amount = rule_data.floor_amount

        financial_rule_repository.add_rule(db_session, rule_model)

        for target_model in _target_models_from_inputs(rule_model.id, user_id, target_inputs):
            financial_rule_repository.add_target(db_session, target_model)

        db_session.flush()
        db_session.commit()
    except IntegrityError as error:
        db_session.rollback()
        raise _translate_integrity_error(error) from error
    except Exception:
        db_session.rollback()
        raise

    return _respond(db_session, rule_model)


# ------------------------------------------------------------------
# Read
# ------------------------------------------------------------------


def get_rules(db_session: Session, user_id: UUID) -> list:
    rule_models = financial_rule_repository.get_rules(db_session, user_id)
    targets = financial_rule_repository.get_targets_for_rules(
        db_session, user_id, [rule.id for rule in rule_models],
    )

    return [_build_response(rule, targets.get(rule.id, [])) for rule in rule_models]


def get_rule(db_session: Session, rule_id: UUID, user_id: UUID):
    rule_model = financial_rule_repository.get_rule_by_id(db_session, rule_id, user_id)

    return _respond(db_session, rule_model)


# ------------------------------------------------------------------
# Update
# ------------------------------------------------------------------


def _current_as_create_dict(
    rule_model: FinancialRuleModel, target_models: list[FinancialRuleGoalTargetModel],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "rule_type": rule_model.rule_type,
        "name": rule_model.name,
        "description": rule_model.description,
    }

    if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
        base.update(
            source_account_id=rule_model.source_account_id,
            execution_mode=rule_model.execution_mode,
            execution_order=rule_model.execution_order,
            effective_from=rule_model.effective_from,
            policy=rule_model.policy,
            percent=rule_model.percent,
            cap_at_target=rule_model.cap_at_target,
            allow_partial=rule_model.allow_partial,
            income_sources=list(rule_model.income_sources or []),
            targets=[
                {"goal_id": t.goal_id, "amount_or_cap": t.amount_or_cap, "position": t.position}
                for t in target_models
            ],
        )
    elif rule_model.rule_type == RULE_TYPE_FLOOR:
        base.update(source_account_id=rule_model.source_account_id, floor_amount=rule_model.floor_amount)
    elif rule_model.rule_type == RULE_TYPE_OVERCOMMITMENT:
        base.update(source_account_id=rule_model.source_account_id)
    else:
        base.update(budget_id=rule_model.budget_id)

    return base


def _normalized_targets(targets: list[Any]) -> dict[UUID, Optional[Decimal]]:
    return {
        (t["goal_id"] if isinstance(t, dict) else t.goal_id): (
            t["amount_or_cap"] if isinstance(t, dict) else t.amount_or_cap
        )
        for t in targets
    }


# Applies a PATCH. A material edit (financial semantics) increments version;
# name, description, execution_order and target positions do not; repeating
# the current values changes nothing. Status is never changed here.
def update_rule(db_session: Session, rule_id: UUID, update_data: FinancialRuleUpdate, user_id: UUID):
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        rule_model = financial_rule_repository.get_rule_by_id_for_update(db_session, rule_id, user_id)
        target_models = financial_rule_repository.get_targets_for_rules(
            db_session, user_id, [rule_model.id],
        ).get(rule_model.id, [])

        provided = set(update_data.model_fields_set)
        allowed = ALLOWED_UPDATE_FIELDS[rule_model.rule_type]

        if provided - allowed:
            raise FinancialRuleInvalidFieldsError(
                "These fields cannot be changed for this rule type: "
                + ", ".join(sorted(provided - allowed))
                + ".",
            )

        for field in provided:
            if getattr(update_data, field) is None and field not in NULLABLE_UPDATE_FIELDS:
                raise FinancialRuleInvalidFieldsError(f"{field} cannot be null.")

        current = _current_as_create_dict(rule_model, target_models)
        merged = dict(current)
        for field in provided:
            value = getattr(update_data, field)
            merged[field] = (
                [t.model_dump() for t in value] if field == "targets" else value
            )

        try:
            validated = financial_rule_create_adapter.validate_python(merged)
        except ValidationError as error:
            first = error.errors()[0]
            raise FinancialRuleInvalidFieldsError(
                f"Invalid rule: {first.get('msg', 'inconsistent fields')}",
            ) from None

        changed_scalar = [
            field for field in MATERIAL_SCALAR_FIELDS[rule_model.rule_type]
            if getattr(validated, field) != current.get(field)
        ]
        material = bool(changed_scalar)
        old_income_sources = sorted(current.get("income_sources", []))

        if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
            if sorted(validated.income_sources) != old_income_sources:
                material = True

            new_targets = _normalized_targets(validated.targets)
            old_targets = _normalized_targets(current["targets"])
            targets_changed = new_targets != old_targets
            material = material or targets_changed
            account_changed = validated.source_account_id != rule_model.source_account_id

            if account_changed or targets_changed:
                added = [goal_id for goal_id in new_targets if goal_id not in old_targets]
                to_check = list(new_targets) if account_changed else added
                _validate_allocation_references(
                    db_session, user_id, validated.source_account_id, to_check,
                    check_account_status=account_changed,
                )
        elif rule_model.rule_type == RULE_TYPE_BUDGET_ALERT:
            if validated.budget_id != rule_model.budget_id:
                budget_repository.get_budget_by_id_for_update(
                    db_session=db_session, budget_id=validated.budget_id, user_id=user_id,
                )
                _assert_subject_unique(
                    db_session, user_id, rule_model.rule_type, None, validated.budget_id, rule_model.id,
                )
        elif validated.source_account_id != rule_model.source_account_id:
            _lock_account(db_session, user_id, validated.source_account_id)
            _assert_subject_unique(
                db_session, user_id, rule_model.rule_type, validated.source_account_id, None, rule_model.id,
            )

        rule_model.name = validated.name
        rule_model.description = validated.description

        if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
            rule_model.source_account_id = validated.source_account_id
            rule_model.execution_mode = validated.execution_mode
            rule_model.execution_order = validated.execution_order
            rule_model.effective_from = validated.effective_from
            rule_model.policy = validated.policy
            rule_model.percent = validated.percent
            rule_model.cap_at_target = validated.cap_at_target
            rule_model.allow_partial = validated.allow_partial
            rule_model.income_sources = list(validated.income_sources)
            _replace_targets(db_session, rule_model, target_models, validated.targets)
        elif rule_model.rule_type == RULE_TYPE_BUDGET_ALERT:
            rule_model.budget_id = validated.budget_id
        else:
            rule_model.source_account_id = validated.source_account_id

            if rule_model.rule_type == RULE_TYPE_FLOOR:
                rule_model.floor_amount = validated.floor_amount

        if material:
            rule_model.version = rule_model.version + 1

            if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
                # A material edit supersedes the rule's open proposals and ends
                # their holds; committed decisions are never re-executed.
                rule_execution_repository.cancel_open_proposals(
                    db_session, user_id, rule_execution_repository.CANCEL_SUPERSEDED,
                    rule_id=rule_model.id,
                )

        db_session.flush()
        db_session.commit()
        db_session.refresh(rule_model)
    except IntegrityError as error:
        db_session.rollback()
        raise _translate_integrity_error(error) from error
    except Exception:
        db_session.rollback()
        raise

    return _respond(db_session, rule_model)


# Replaces the target set in place: existing rows for a kept Goal are updated
# (their ids survive), removed Goals are deleted first, new Goals inserted.
def _replace_targets(
    db_session: Session,
    rule_model: FinancialRuleModel,
    existing: list[FinancialRuleGoalTargetModel],
    new_inputs: list[FinancialRuleGoalTargetInput],
) -> None:
    by_goal = {target.goal_id: target for target in existing}
    wanted = {target.goal_id for target in new_inputs}

    for goal_id, target in by_goal.items():
        if goal_id not in wanted:
            financial_rule_repository.delete_target(db_session, target)

    db_session.flush()

    for index, target_input in enumerate(new_inputs):
        position = target_input.position if target_input.position is not None else index
        row = by_goal.get(target_input.goal_id)

        if row is None:
            financial_rule_repository.add_target(
                db_session,
                FinancialRuleGoalTargetModel(
                    id=uuid4(), rule_id=rule_model.id, user_id=rule_model.user_id,
                    goal_id=target_input.goal_id, amount_or_cap=target_input.amount_or_cap,
                    position=position,
                ),
            )
        else:
            row.amount_or_cap = target_input.amount_or_cap
            row.position = position


# ------------------------------------------------------------------
# Status transitions
# ------------------------------------------------------------------


# VF-020E7/E8: AUTO and CONFIRM income-allocation rules can be enabled (no
# hidden "previewed" state exists; the preview is a UX rule). Enabling re-runs the
# current validation (active Account and Goals, equal currencies) so a rule that
# is already invalid cannot be activated; pause and disable are always allowed
# by the status machine.
def _assert_allocation_rule_transition_available(
    db_session: Session, user_id: UUID, rule_model: FinancialRuleModel, action: str,
) -> None:
    if action != "enable":
        return

    targets = financial_rule_repository.get_targets_for_rules(
        db_session, user_id, [rule_model.id],
    ).get(rule_model.id, [])

    _validate_allocation_references(
        db_session=db_session,
        user_id=user_id,
        source_account_id=rule_model.source_account_id,
        goal_ids_to_check=[target.goal_id for target in targets],
        check_account_status=True,
    )


def _transition(db_session: Session, rule_id: UUID, user_id: UUID, action: str):
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        rule_model = financial_rule_repository.get_rule_by_id_for_update(db_session, rule_id, user_id)

        if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
            _assert_allocation_rule_transition_available(
                db_session, user_id, rule_model, action,
            )
        elif rule_model.rule_type in (RULE_TYPE_OVERCOMMITMENT, RULE_TYPE_BUDGET_ALERT):
            # Alert rules (VF-020E9B) can be enabled only where the E9A schema
            # exists: a rule must never look operational when nothing can store
            # its alerts (the runtime is deployed before the production
            # migration is applied).
            if action == "enable" and not rule_alert_repository.table_exists(db_session):
                raise FinancialRuleActivationNotAvailableError()

        allowed_from = {
            "enable": ("draft", "paused", "disabled"),
            "pause": ("enabled",),
            "disable": ("enabled", "paused"),
        }[action]

        if rule_model.status not in allowed_from:
            raise FinancialRuleInvalidTransitionError()

        rule_model.status = {"enable": "enabled", "pause": "paused", "disable": "disabled"}[action]

        if action in ("pause", "disable") and rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION:
            # Open proposals of an inactive rule can no longer be confirmed;
            # completed allocations are untouched.
            rule_execution_repository.cancel_open_proposals(
                db_session, user_id, rule_execution_repository.CANCEL_RULE_INACTIVE,
                rule_id=rule_model.id,
            )

        if action == "enable":
            # Every transition into enabled resets active_since.
            rule_model.active_since = func.now()

            # effective_from defaults to the server date of the FIRST
            # activation and never moves on later enables (§10.3).
            if rule_model.rule_type == RULE_TYPE_INCOME_ALLOCATION and rule_model.effective_from is None:
                rule_model.effective_from = date.today()

        db_session.flush()
        db_session.commit()
        db_session.refresh(rule_model)
    except Exception:
        db_session.rollback()
        raise

    return _respond(db_session, rule_model)


def enable_rule(db_session: Session, rule_id: UUID, user_id: UUID):
    return _transition(db_session, rule_id, user_id, "enable")


def pause_rule(db_session: Session, rule_id: UUID, user_id: UUID):
    return _transition(db_session, rule_id, user_id, "pause")


def disable_rule(db_session: Session, rule_id: UUID, user_id: UUID):
    return _transition(db_session, rule_id, user_id, "disable")


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


# Deletes a draft or disabled rule without execution history; its targets go
# with it (database cascade). A rule with any rule_executions row is a
# controlled 409 (APPROVED P57): the user must disable it instead. The
# pre-check runs under L0 and the rule lock, before the RESTRICT foreign key,
# so the caller never sees a raw IntegrityError.
def delete_rule(db_session: Session, rule_id: UUID, user_id: UUID) -> None:
    try:
        goal_user_lock.acquire_goal_user_lock(db_session, user_id)

        rule_model = financial_rule_repository.get_rule_by_id_for_update(db_session, rule_id, user_id)

        if rule_model.status not in ("draft", "disabled"):
            raise FinancialRuleDeletionNotAllowedError()

        if rule_execution_repository.rule_has_executions(db_session, rule_id, user_id):
            raise FinancialRuleDeletionNotAllowedError()

        financial_rule_repository.delete_rule(db_session, rule_model)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
