from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.budgets import budget_repository, budget_version_repository
from app.modules.budgets.budget_errors import (
    BudgetImmutableFieldError,
    BudgetRetroactiveDeactivationError,
)
from app.modules.budgets.budget_period import resolve_period
from app.modules.budgets.budget_schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
)
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories import service as categories_service

VERSION_CHANGE_REASON_INITIAL = "initial"
VERSION_CHANGE_REASON_USER_EDIT = "user_edit"
VERSION_CHANGE_REASON_CATEGORY_CHANGE = "category_change"


# Creates a new budget using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget creation data.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetResponse created from the saved database model.
# Raises:
# - CategoryNotFoundError: when category_id is set and the category does not
#   exist or does not belong to the authenticated user.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
    user_id: UUID,
) -> BudgetResponse:
    if budget_data.category_id is not None:
        # A budget can only reference a category the authenticated user owns.
        # This mirrors the expense category ownership check so cross-user
        # category ids are rejected before persistence.
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=budget_data.category_id,
            user_id=user_id,
        )

    # A budget must never exist without its initial version (or vice versa),
    # so both writes are flushed under one transaction and committed together
    # here in the service layer - the repositories only add/flush.
    try:
        budget_model = budget_repository.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
            commit=False,
        )

        # Every budget gets exactly one 'initial' version at creation,
        # anchored to the period containing its activation date. This is
        # what lets a later limit/category edit floor its effective_from to
        # "the current period" instead of "whatever the budget originally
        # started at".
        initial_period = resolve_period(budget_model.period, budget_model.start_date)
        budget_version_repository.create_version(
            db_session=db_session,
            budget_id=budget_model.id,
            user_id=user_id,
            effective_from=initial_period.period_start,
            effective_until=None,
            limit_amount=budget_model.limit_amount,
            category_id=budget_model.category_id,
            change_reason=VERSION_CHANGE_REASON_INITIAL,
            commit=False,
        )

        db_session.commit()
        db_session.refresh(budget_model)
    except Exception:
        db_session.rollback()
        raise

    return BudgetResponse.model_validate(budget_model)


# Returns budgets for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter budgets.
# Returns:
# - List of BudgetResponse objects.
def get_budgets(
    db_session: Session,
    user_id: UUID,
) -> list[BudgetResponse]:
    budget_models = budget_repository.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        BudgetResponse.model_validate(budget_model)
        for budget_model in budget_models
    ]


# Determines whether a budget's first period has already completed as of
# a reference date.
# This function exists because period/start_date edits are only allowed
# during a short typo-fix window: before the calendar has moved past the
# period the budget was originally activated in.
# Parameters:
# - budget_model: the budget's current (pre-update) database model.
# - as_of: reference date, normally today.
# Returns:
# - True if as_of still falls within the budget's original first period.
def _is_within_first_period(budget_model: BudgetModel, as_of: date) -> bool:
    first_period = resolve_period(budget_model.period, budget_model.start_date)
    return as_of <= first_period.period_end


# Updates an existing budget owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - budget_data: validated partial budget update data.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetResponse created from the updated database model.
# Raises:
# - BudgetNotFoundError: when the budget does not exist or does not belong
#   to the authenticated user.
# - CategoryNotFoundError: when category_id is being changed to a non-null
#   value and the category does not exist or does not belong to the
#   authenticated user.
# - BudgetImmutableFieldError: when currency is changed at all, or period/
#   start_date is changed after the budget's first period has completed.
# - BudgetRetroactiveDeactivationError: when end_date is set to a date
#   before today.
def update_budget(
    db_session: Session,
    budget_id: UUID,
    budget_data: BudgetUpdate,
    user_id: UUID,
) -> BudgetResponse:
    existing_budget = budget_repository.get_budget_by_id(
        db_session=db_session,
        budget_id=budget_id,
        user_id=user_id,
    )

    fields_set = budget_data.model_fields_set
    today = date.today()

    if "currency" in fields_set:
        # Currency is never editable: re-denominating a limit changes the
        # real value it represents, and this product is single-base-currency.
        raise BudgetImmutableFieldError()

    redefines_first_period = False

    if ("period" in fields_set or "start_date" in fields_set) and (
        budget_data.period != existing_budget.period
        or budget_data.start_date != existing_budget.start_date
    ):
        if not _is_within_first_period(existing_budget, today):
            # Changing period/start_date after periods have already
            # occurred would make those periods non-reconstructible.
            raise BudgetImmutableFieldError()

        redefines_first_period = True

    if (
        "end_date" in fields_set
        and budget_data.end_date is not None
        and budget_data.end_date < today
    ):
        # Retroactively deactivating a budget would erase already-completed
        # periods that were counted against it.
        raise BudgetRetroactiveDeactivationError()

    if (
        "category_id" in budget_data.model_fields_set
        and budget_data.category_id is not None
    ):
        # Only validate ownership when category_id is explicitly being
        # changed to a non-null value. An omitted category_id must not
        # trigger a lookup, and an explicit null clears the category
        # without needing ownership validation.
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=budget_data.category_id,
            user_id=user_id,
        )

    limit_amount_changed = (
        "limit_amount" in fields_set
        and budget_data.limit_amount != existing_budget.limit_amount
    )
    category_changed = (
        "category_id" in fields_set
        and budget_data.category_id != existing_budget.category_id
    )

    # The budget row change and any version write it implies must land
    # together or not at all - a failure writing history must never leave
    # the budget row committed in a state history does not represent. Both
    # writes are flushed under one transaction and committed together here;
    # the repositories only add/flush.
    try:
        budget_model = budget_repository.update_budget(
            db_session=db_session,
            budget_id=budget_id,
            budget_data=budget_data,
            user_id=user_id,
            commit=False,
        )

        if redefines_first_period:
            # Only reachable before the budget's first period has completed,
            # so no real period has been "locked in" yet - replace the
            # history instead of appending to it, so it reflects the
            # corrected definition rather than a stale one.
            budget_version_repository.delete_versions_for_budget(
                db_session=db_session,
                budget_id=budget_model.id,
                commit=False,
            )
            corrected_period = resolve_period(budget_model.period, budget_model.start_date)
            budget_version_repository.create_version(
                db_session=db_session,
                budget_id=budget_model.id,
                user_id=user_id,
                effective_from=corrected_period.period_start,
                effective_until=None,
                limit_amount=budget_model.limit_amount,
                category_id=budget_model.category_id,
                change_reason=VERSION_CHANGE_REASON_INITIAL,
                commit=False,
            )
        elif limit_amount_changed or category_changed:
            current_period = resolve_period(budget_model.period, today)
            change_reason = (
                VERSION_CHANGE_REASON_CATEGORY_CHANGE
                if category_changed
                else VERSION_CHANGE_REASON_USER_EDIT
            )
            budget_version_repository.create_version(
                db_session=db_session,
                budget_id=budget_model.id,
                user_id=user_id,
                effective_from=current_period.period_start,
                effective_until=None,
                limit_amount=budget_model.limit_amount,
                category_id=budget_model.category_id,
                change_reason=change_reason,
                commit=False,
            )

        db_session.commit()
        db_session.refresh(budget_model)
    except Exception:
        db_session.rollback()
        raise

    return BudgetResponse.model_validate(budget_model)


# Deletes an existing budget owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - None.
def delete_budget(
    db_session: Session,
    budget_id: UUID,
    user_id: UUID,
) -> None:
    budget_repository.delete_budget(
        db_session=db_session,
        budget_id=budget_id,
        user_id=user_id,
    )
