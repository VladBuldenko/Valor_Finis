from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.financial_settings import financial_settings_service
from app.modules.fx import fx_service
from app.modules.fx.fx_errors import FxFutureDatedNotSupportedError
from app.modules.fx.fx_schemas import FxRateResult
from app.modules.income import income_repository
from app.modules.income.income_errors import IncomeFutureDatedNotSupportedError
from app.modules.income.income_schemas import (
    IncomeCreate,
    IncomeResponse,
    IncomeUpdate,
)

BASE_AMOUNT_DECIMAL_PLACES = Decimal("0.01")

# Matches the fx_rate column's NUMERIC(18,8) scale - identical rationale to
# expenses_service.FX_RATE_DECIMAL_PLACES: base_amount must be derived
# from the rate at exactly the precision that gets persisted, not from a
# wider in-memory value, so a row read back from PostgreSQL satisfies its
# own invariant: base_amount == (amount * fx_rate).quantize(BASE_AMOUNT_DECIMAL_PLACES).
FX_RATE_DECIMAL_PLACES = Decimal("0.00000001")


# Resolves the FX snapshot for an income transaction, translating the
# shared fx_service future-dated error into this domain's own public
# error.
# This function exists as the single seam both create_income and
# update_income call through, so the FxFutureDatedNotSupportedError ->
# IncomeFutureDatedNotSupportedError translation happens in exactly one
# place. fx_service.resolve_fx_rate itself is reused completely unmodified
# - this function does not duplicate or reimplement any FX resolution
# logic, it only adapts the error type at the boundary so Income carries
# its own public message ("income" vs "expense") without Expense's
# error class or mapped message ever being touched.
# Parameters:
# - original_currency: the income's own currency code.
# - base_currency: the user's base currency code.
# - transaction_date: the income's received_at - the historical date FX
#   truth is resolved for.
# - as_of: reference "today", used only to reject a future-dated foreign
#   transaction.
# Returns:
# - FxRateResult in the canonical base-per-original direction.
# Raises:
# - IncomeFutureDatedNotSupportedError: a foreign-currency income dated
#   after as_of.
# - FxRateUnavailableError/FxProviderUnavailableError: unchanged, reused
#   as-is - these are already domain-neutral.
def _resolve_income_fx_rate(
    original_currency: str,
    base_currency: str,
    transaction_date: date,
    as_of: date,
) -> FxRateResult:
    try:
        return fx_service.resolve_fx_rate(
            original_currency=original_currency,
            base_currency=base_currency,
            transaction_date=transaction_date,
            as_of=as_of,
        )
    except FxFutureDatedNotSupportedError:
        raise IncomeFutureDatedNotSupportedError()


# Creates a new income record using validated income data and
# authenticated user id.
# This function exists to keep business logic separate from API and
# database layers. Resolves the FX snapshot before persisting anything:
# the user's base currency, then a historical rate for received_at, then
# base_amount - all before the income row is constructed at all, so a
# provider failure leaves no Income row created. Mirrors
# expenses_service.create_expense exactly, minus the category ownership
# check (Income has no category_id in this slice).
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_data: validated income input data.
# - user_id: authenticated user identifier that owns the income record.
# - commit: whether the income record should be committed immediately.
# Returns:
# - IncomeResponse object created from the saved database model.
# Raises:
# - IncomeFutureDatedNotSupportedError: received_at is in the future and
#   currency differs from the user's base currency.
# - FxRateUnavailableError: currency/base_currency pairing is not
#   supported, or no historical rate could be resolved.
# - FxProviderUnavailableError: the FX provider failed transiently.
def create_income(
    db_session: Session,
    income_data: IncomeCreate,
    user_id: UUID,
    commit: bool = True,
) -> IncomeResponse:
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
        commit=False,
    )

    fx_result = _resolve_income_fx_rate(
        original_currency=income_data.currency,
        base_currency=base_currency,
        transaction_date=income_data.received_at,
        as_of=date.today(),
    )

    # Normalize the canonical rate to exactly the precision that will be
    # persisted (fx_rate is NUMERIC(18,8)) before it is used for anything -
    # same reasoning as expenses_service.create_expense.
    stored_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)

    base_amount = (income_data.amount * stored_fx_rate).quantize(
        BASE_AMOUNT_DECIMAL_PLACES,
    )

    income_model = income_repository.create_income(
        db_session=db_session,
        income_data=income_data,
        user_id=user_id,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=stored_fx_rate,
        fx_rate_date=fx_result.actual_rate_date,
        fx_source=fx_result.source,
        commit=commit,
    )

    return IncomeResponse.model_validate(income_model)


# Returns income records for the authenticated user.
# This function exists to keep response mapping outside the repository
# layer and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter income records.
# Returns:
# - List of IncomeResponse objects, newest received_at first.
def get_income(
    db_session: Session,
    user_id: UUID,
) -> list[IncomeResponse]:
    income_models = income_repository.get_income(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        IncomeResponse.model_validate(income_model)
        for income_model in income_models
    ]


# Updates an existing income record owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
#
# FX snapshot rule, decided entirely before any write happens (identical
# structure to expenses_service.update_expense):
# - non-monetary fields only (source/description): snapshot copied
#   unchanged, no provider call.
# - amount changed, currency/received_at unchanged: reuse the stored
#   fx_rate/fx_rate_date/fx_source, only recompute base_amount from the
#   new amount.
# - currency and/or received_at changed: resolve a full snapshot exactly
#   once, using the final amount/currency/date.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - income_data: validated partial income update data.
# - user_id: authenticated user identifier that owns the income record.
# Returns:
# - IncomeResponse object created from the updated database model.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
# - IncomeFutureDatedNotSupportedError/FxRateUnavailableError/
#   FxProviderUnavailableError: see create_income - only raised when a
#   monetary field actually changed and a fresh resolution was required.
def update_income(
    db_session: Session,
    income_id: UUID,
    income_data: IncomeUpdate,
    user_id: UUID,
) -> IncomeResponse:
    existing_income = income_repository.get_income_by_id(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    fields_set = income_data.model_fields_set
    monetary_fields_changed = bool({"amount", "currency", "received_at"} & fields_set)

    if not monetary_fields_changed:
        # Metadata-only update (source/description): the existing
        # snapshot is left exactly as it was - never forces a network
        # call.
        resolved_base_amount = existing_income.base_amount
        resolved_base_currency = existing_income.base_currency
        resolved_fx_rate = existing_income.fx_rate
        resolved_fx_rate_date = existing_income.fx_rate_date
        resolved_fx_source = existing_income.fx_source
    else:
        final_currency = (
            income_data.currency if "currency" in fields_set else existing_income.currency
        )
        final_received_at = (
            income_data.received_at
            if "received_at" in fields_set
            else existing_income.received_at
        )
        final_amount = (
            income_data.amount if "amount" in fields_set else existing_income.amount
        )

        currency_or_date_changed = (
            final_currency != existing_income.currency
            or final_received_at != existing_income.received_at
        )

        if not currency_or_date_changed:
            # amount-only change against the existing snapshot: reuse the
            # stored rate, never re-fetch.
            resolved_base_currency = existing_income.base_currency
            resolved_fx_rate = existing_income.fx_rate
            resolved_fx_rate_date = existing_income.fx_rate_date
            resolved_fx_source = existing_income.fx_source
        else:
            # currency and/or received_at changed: resolve exactly once
            # against the final values.
            resolved_base_currency = financial_settings_service.get_base_currency(
                db_session=db_session,
                user_id=user_id,
                commit=False,
            )

            fx_result = _resolve_income_fx_rate(
                original_currency=final_currency,
                base_currency=resolved_base_currency,
                transaction_date=final_received_at,
                as_of=date.today(),
            )

            # Same persisted-precision normalization as create_income -
            # see FX_RATE_DECIMAL_PLACES.
            resolved_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)
            resolved_fx_rate_date = fx_result.actual_rate_date
            resolved_fx_source = fx_result.source

        resolved_base_amount = (final_amount * resolved_fx_rate).quantize(
            BASE_AMOUNT_DECIMAL_PLACES,
        )

    income_model = income_repository.update_income(
        db_session=db_session,
        income_id=income_id,
        income_data=income_data,
        user_id=user_id,
        base_amount=resolved_base_amount,
        base_currency=resolved_base_currency,
        fx_rate=resolved_fx_rate,
        fx_rate_date=resolved_fx_rate_date,
        fx_source=resolved_fx_source,
    )

    return IncomeResponse.model_validate(income_model)


# Deletes an existing income record owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - user_id: authenticated user identifier that owns the income record.
# Returns:
# - None.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
def delete_income(
    db_session: Session,
    income_id: UUID,
    user_id: UUID,
) -> None:
    income_repository.delete_income(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )
