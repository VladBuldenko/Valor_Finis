from datetime import date
from decimal import Decimal
from uuid import UUID

from app.modules.categories import service as categories_service
from sqlalchemy.orm import Session

from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_schemas import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
)
from app.modules.financial_settings import financial_settings_service
from app.modules.fx import fx_service

BASE_AMOUNT_DECIMAL_PLACES = Decimal("0.01")

# Matches the fx_rate column's NUMERIC(18,8) scale. A provider's canonical
# rate (e.g. Decimal("1") / published_rate) carries far more than 8 decimal
# digits; base_amount must be derived from the rate at exactly the
# precision that gets persisted, not from the wider in-memory value,
# otherwise a row read back from PostgreSQL would fail its own invariant:
# base_amount == (amount * fx_rate).quantize(BASE_AMOUNT_DECIMAL_PLACES).
FX_RATE_DECIMAL_PLACES = Decimal("0.00000001")


# Creates a new expense using validated expense data and authenticated user id.
# This function exists to keep business logic separate
# from API and database layers.
# Resolves the VF-014B5C FX snapshot before persisting anything: the
# user's base currency (VF-014B5B), then a historical rate for
# expense_date, then base_amount - all before the expense row is
# constructed at all, so a provider failure leaves no Expense row created.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data.
# - user_id: authenticated user identifier that owns the expense.
# - commit: whether the expense should be committed immediately.
# Returns:
# - ExpenseResponse object created from the saved database model.
# Raises:
# - CategoryNotFoundError: when category_id is set and the category does
#   not exist or does not belong to the authenticated user.
# - FxFutureDatedNotSupportedError: expense_date is in the future and
#   currency differs from the user's base currency.
# - FxRateUnavailableError: currency/base_currency pairing is not
#   supported, or no historical rate could be resolved.
# - FxProviderUnavailableError: the FX provider failed transiently.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
    user_id: UUID,
    commit: bool = True,
) -> ExpenseResponse:
    if expense_data.category_id is not None:
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=expense_data.category_id,
            user_id=user_id,
        )

    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
        commit=False,
    )

    fx_result = fx_service.resolve_fx_rate(
        original_currency=expense_data.currency,
        base_currency=base_currency,
        transaction_date=expense_data.expense_date,
        as_of=date.today(),
    )

    # Normalize the canonical rate to exactly the precision that will be
    # persisted (fx_rate is NUMERIC(18,8)) before it is used for anything,
    # so the stored fx_rate and the stored base_amount are always
    # reproducible from each other with no hidden extra precision.
    stored_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)

    base_amount = (expense_data.amount * stored_fx_rate).quantize(
        BASE_AMOUNT_DECIMAL_PLACES,
    )

    expense_model = expenses_repository.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=stored_fx_rate,
        fx_rate_date=fx_result.actual_rate_date,
        fx_source=fx_result.source,
        commit=commit,
    )

    return ExpenseResponse.model_validate(expense_model)

# Returns expenses for the authenticated user.
# This function exists to keep response mapping outside the repository layer
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# Returns:
# - List of ExpenseResponse objects.
def get_expenses(
    db_session: Session,
    user_id: UUID,
) -> list[ExpenseResponse]:
    expense_models = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        ExpenseResponse.model_validate(expense_model)
        for expense_model in expense_models
    ]


# Updates an existing expense owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
#
# VF-014B5C FX snapshot rule, decided entirely before any write happens:
# - non-monetary fields only (category_id/title/description/source):
#   snapshot copied unchanged, no provider call.
# - amount changed, currency/expense_date unchanged, and a real snapshot
#   already exists: reuse the stored fx_rate/fx_rate_date/fx_source,
#   only recompute base_amount from the new amount.
# - currency and/or expense_date changed, OR this is a legacy unresolved
#   expense (no snapshot yet) now receiving a monetary update: resolve a
#   full snapshot exactly once, using the final amount/currency/date.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - expense_data: validated partial expense update data.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseResponse object created from the updated database model.
# Raises:
# - CategoryNotFoundError: when category_id is being changed to a non-null
#   value and the category does not exist or does not belong to the
#   authenticated user.
# - FxFutureDatedNotSupportedError/FxRateUnavailableError/
#   FxProviderUnavailableError: see create_expense - only raised when a
#   monetary field actually changed and a fresh resolution was required.
def update_expense(
    db_session: Session,
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    user_id: UUID,
) -> ExpenseResponse:
    existing_expense = expenses_repository.get_expense_by_id(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    if (
        "category_id" in expense_data.model_fields_set
        and expense_data.category_id is not None
    ):
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=expense_data.category_id,
            user_id=user_id,
        )

    fields_set = expense_data.model_fields_set
    monetary_fields_changed = bool({"amount", "currency", "expense_date"} & fields_set)

    if not monetary_fields_changed:
        # Metadata-only update: the snapshot (resolved or unresolved) is
        # left exactly as it was - never forces a network call.
        resolved_base_amount = existing_expense.base_amount
        resolved_base_currency = existing_expense.base_currency
        resolved_fx_rate = existing_expense.fx_rate
        resolved_fx_rate_date = existing_expense.fx_rate_date
        resolved_fx_source = existing_expense.fx_source
    else:
        final_currency = (
            expense_data.currency if "currency" in fields_set else existing_expense.currency
        )
        final_expense_date = (
            expense_data.expense_date
            if "expense_date" in fields_set
            else existing_expense.expense_date
        )
        final_amount = (
            expense_data.amount if "amount" in fields_set else existing_expense.amount
        )

        currency_or_date_changed = (
            final_currency != existing_expense.currency
            or final_expense_date != existing_expense.expense_date
        )

        if not currency_or_date_changed and existing_expense.base_amount is not None:
            # amount-only change against an already-resolved snapshot:
            # reuse the stored rate, never re-fetch.
            resolved_base_currency = existing_expense.base_currency
            resolved_fx_rate = existing_expense.fx_rate
            resolved_fx_rate_date = existing_expense.fx_rate_date
            resolved_fx_source = existing_expense.fx_source
        else:
            # currency and/or expense_date changed, or this legacy row
            # has no snapshot yet: resolve exactly once against the
            # final values.
            resolved_base_currency = financial_settings_service.get_base_currency(
                db_session=db_session,
                user_id=user_id,
                commit=False,
            )

            fx_result = fx_service.resolve_fx_rate(
                original_currency=final_currency,
                base_currency=resolved_base_currency,
                transaction_date=final_expense_date,
                as_of=date.today(),
            )

            # Same persisted-precision normalization as create_expense -
            # see FX_RATE_DECIMAL_PLACES.
            resolved_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)
            resolved_fx_rate_date = fx_result.actual_rate_date
            resolved_fx_source = fx_result.source

        resolved_base_amount = (final_amount * resolved_fx_rate).quantize(
            BASE_AMOUNT_DECIMAL_PLACES,
        )

    expense_model = expenses_repository.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=user_id,
        base_amount=resolved_base_amount,
        base_currency=resolved_base_currency,
        fx_rate=resolved_fx_rate,
        fx_rate_date=resolved_fx_rate_date,
        fx_source=resolved_fx_source,
    )

    return ExpenseResponse.model_validate(expense_model)

# Deletes an existing expense owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - None.
def delete_expense(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> None:
    expenses_repository.delete_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )
