from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_errors import AccountArchivedError
from app.modules.accounts.account_models import AccountModel
from app.modules.financial_settings import financial_settings_service
from app.modules.fx import fx_service
from app.modules.fx.fx_errors import FxFutureDatedNotSupportedError
from app.modules.fx.fx_schemas import FxRateResult
from app.modules.income import income_repository
from app.modules.income.income_errors import (
    IncomeAccountCurrencyMismatchError,
    IncomeFutureDatedNotSupportedError,
)
from app.modules.income.income_models import IncomeModel
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


# Validates that an Account can receive a NEW linked-Income relationship
# (create, attach, or move-in).
# This function exists for the two cases where linking adds activity to
# the destination Account - an archived Account must never gain a new
# credit. It must never be used for the "stays linked to the same
# Account" case, where the Account's archived status is irrelevant (see
# _validate_income_currency_matches_account below) and for the "move-out"
# side of a move, which has no validation at all (VF-017D: archived
# status only ever blocks the destination of new activity, never a
# source being corrected/vacated).
# Parameters:
# - account_model: the target Account, already locked by the caller.
# - income_currency: the Income's own (final) currency code.
# Returns:
# - None.
# Raises:
# - AccountArchivedError: the target Account is archived.
# - IncomeAccountCurrencyMismatchError: currencies do not match exactly.
def _validate_income_account_link(
    account_model: AccountModel,
    income_currency: str,
) -> None:
    if account_model.status == "archived":
        raise AccountArchivedError()

    _validate_income_currency_matches_account(account_model, income_currency)


# Validates only that an Income's currency matches an Account's currency,
# with no archived-status check.
# This function exists for the "stays linked to the same Account" case:
# correcting/synchronizing an Income that is already linked is never
# blocked by that Account having been archived afterward (VF-017D) - only
# a currency mismatch is ever rejected there.
# Parameters:
# - account_model: the Account the Income remains linked to.
# - income_currency: the Income's own (final) currency code.
# Returns:
# - None.
# Raises:
# - IncomeAccountCurrencyMismatchError: currencies do not match exactly.
def _validate_income_currency_matches_account(
    account_model: AccountModel,
    income_currency: str,
) -> None:
    if income_currency != account_model.currency:
        raise IncomeAccountCurrencyMismatchError()


# Builds an IncomeResponse from an Income model and an already-resolved
# account_id.
# This function exists because IncomeResponse.model_validate(income_model)
# is no longer sufficient on its own (VF-017D): account_id has no
# database column to read via ORM attribute access at all - it must
# always be supplied explicitly, by a caller that has already resolved it
# (a single lookup for create/update, or a bulk-resolved mapping for
# get_income). This is the only function in this module that constructs
# an IncomeResponse, so there is exactly one place account_id's source
# can ever be wrong.
# Parameters:
# - income_model: the Income database record.
# - account_id: the Account this Income is currently linked to, or None.
# Returns:
# - IncomeResponse with account_id set to the given, already-derived
#   value.
def _build_income_response(
    income_model: IncomeModel,
    account_id: Optional[UUID],
) -> IncomeResponse:
    return IncomeResponse(
        id=income_model.id,
        user_id=income_model.user_id,
        amount=income_model.amount,
        currency=income_model.currency,
        received_at=income_model.received_at,
        source=income_model.source,
        description=income_model.description,
        account_id=account_id,
        base_amount=income_model.base_amount,
        base_currency=income_model.base_currency,
        fx_rate=income_model.fx_rate,
        fx_rate_date=income_model.fx_rate_date,
        fx_source=income_model.fx_source,
        created_at=income_model.created_at,
        updated_at=income_model.updated_at,
    )


# Creates a new income record using validated income data and
# authenticated user id, optionally linking it to an Account atomically.
# This function exists to keep business logic separate from API and
# database layers. The Income's own FX snapshot is always resolved first
# - before any Account row is locked - because FX resolution can perform
# real network I/O (ECB/NBU) and an Account SELECT ... FOR UPDATE lock
# must never be held across a network call (VF-017D). For an unlinked
# create this is the entire operation, unchanged from VF-017C. For a
# linked create: lock the target Account, validate it (owned by this
# user, not archived, exact currency match), insert the Income, insert
# its AccountTransaction projection, one commit - if validation fails,
# neither row is written.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_data: validated income input data, optionally including
#   account_id.
# - user_id: authenticated user identifier that owns the income record.
# - commit: whether the whole operation should be committed immediately.
# Returns:
# - IncomeResponse object created from the saved database model, with
#   account_id reflecting the (possibly newly-created) linkage.
# Raises:
# - AccountNotFoundError: account_id does not exist or is not owned by
#   this user.
# - AccountArchivedError: account_id refers to an archived Account.
# - IncomeAccountCurrencyMismatchError: the Income's currency does not
#   exactly match the Account's currency.
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

    stored_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)
    base_amount = (income_data.amount * stored_fx_rate).quantize(
        BASE_AMOUNT_DECIMAL_PLACES,
    )

    if income_data.account_id is None:
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
        return _build_income_response(income_model, account_id=None)

    # Linked create: FX resolution above already happened before any
    # Account lock - now lock the Account and validate before writing
    # anything at all.
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session,
        account_id=income_data.account_id,
        user_id=user_id,
    )
    _validate_income_account_link(account_model, income_data.currency)

    income_model = income_repository.create_income(
        db_session=db_session,
        income_data=income_data,
        user_id=user_id,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=stored_fx_rate,
        fx_rate_date=fx_result.actual_rate_date,
        fx_source=fx_result.source,
        commit=False,
    )

    account_transaction_repository.create_income_projection(
        db_session=db_session,
        account_id=account_model.id,
        income_id=income_model.id,
        user_id=user_id,
        amount=income_model.amount,
        transaction_date=income_model.received_at,
        commit=False,
    )

    if commit:
        db_session.commit()
        db_session.refresh(income_model)

    return _build_income_response(income_model, account_id=account_model.id)


# Returns income records for the authenticated user, each with its
# currently-linked account_id (or None) resolved.
# This function exists to keep response mapping outside the repository
# layer and to ensure service-level reads are always scoped to a user.
# account_id is resolved with exactly one bulk query for the whole list
# (get_income_account_links_for_user), never one projection lookup per
# Income (VF-017D).
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

    account_links = account_transaction_repository.get_income_account_links_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        _build_income_response(income_model, account_links.get(income_model.id))
        for income_model in income_models
    ]


# Updates an existing income record owned by the authenticated user,
# evaluating the PATCH against its FINAL state - never field by field in
# isolation - and keeping any Account linkage synchronized atomically.
#
# Locking order (VF-017D): the Income row is locked FIRST
# (get_income_by_id_for_update), and its current Account projection is
# resolved only after that lock is held - reading "which Account is this
# currently linked to" before locking Income would be a stale-read TOCTOU
# window, since that fact is itself derived from a projection a
# concurrent request could change. Only once the final linkage state is
# known are the required Account row(s) locked - one Account for
# attach/detach/stay, two (in ascending UUID order, to avoid deadlocking
# against a concurrent opposite-direction move) for a move. If a fresh FX
# resolution is required, it happens BEFORE any Account lock is taken,
# for the same never-hold-a-lock-across-network-I/O reason as
# create_income. No Account is locked at all when the Income stays
# unlinked and no monetary field is changing (a pure source/description
# edit never touches this domain).
#
# FX snapshot rule (unchanged from VF-017C): amount alone reuses the
# existing rate; currency and/or received_at changing triggers a full
# fresh resolution; source/description-only changes never call the
# provider.
#
# Archived-Account rule (VF-017D): rejected only when the operation adds
# NEW activity to an Account - attaching, or moving INTO an archived
# Account. Never rejected for amount/date corrections to an Income
# already linked to an Account that was archived afterward, and never
# rejected for detaching or moving OUT of an archived Account - those are
# corrections/removals of existing history, not new activity.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - income_data: validated partial income update data, evaluated as a
#   whole (final state), including any account_id change.
# - user_id: authenticated user identifier that owns the income record.
# Returns:
# - IncomeResponse object created from the updated database model, with
#   account_id reflecting the resulting linkage.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
# - AccountNotFoundError: a referenced account_id does not exist or is
#   not owned by this user.
# - AccountArchivedError: new activity (attach/move-in) targets an
#   archived Account.
# - IncomeAccountCurrencyMismatchError: the final currency does not
#   exactly match the final linked Account's currency.
# - IncomeFutureDatedNotSupportedError/FxRateUnavailableError/
#   FxProviderUnavailableError: see create_income - only raised when a
#   monetary field actually changed and a fresh resolution was required.
def update_income(
    db_session: Session,
    income_id: UUID,
    income_data: IncomeUpdate,
    user_id: UUID,
) -> IncomeResponse:
    income_model = income_repository.get_income_by_id_for_update(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    current_projection = account_transaction_repository.get_income_projection(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )
    current_account_id = current_projection.account_id if current_projection else None

    fields_set = income_data.model_fields_set
    final_account_id = (
        income_data.account_id if "account_id" in fields_set else current_account_id
    )

    monetary_fields_changed = bool({"amount", "currency", "received_at"} & fields_set)

    final_currency = (
        income_data.currency if "currency" in fields_set else income_model.currency
    )
    final_received_at = (
        income_data.received_at
        if "received_at" in fields_set
        else income_model.received_at
    )
    final_amount = (
        income_data.amount if "amount" in fields_set else income_model.amount
    )

    # FX resolution (if needed) happens before any Account lock is taken.
    if not monetary_fields_changed:
        resolved_base_amount = income_model.base_amount
        resolved_base_currency = income_model.base_currency
        resolved_fx_rate = income_model.fx_rate
        resolved_fx_rate_date = income_model.fx_rate_date
        resolved_fx_source = income_model.fx_source
    else:
        currency_or_date_changed = (
            final_currency != income_model.currency
            or final_received_at != income_model.received_at
        )

        if not currency_or_date_changed:
            resolved_base_currency = income_model.base_currency
            resolved_fx_rate = income_model.fx_rate
            resolved_fx_rate_date = income_model.fx_rate_date
            resolved_fx_source = income_model.fx_source
        else:
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

            resolved_fx_rate = fx_result.rate.quantize(FX_RATE_DECIMAL_PLACES)
            resolved_fx_rate_date = fx_result.actual_rate_date
            resolved_fx_source = fx_result.source

        resolved_base_amount = (final_amount * resolved_fx_rate).quantize(
            BASE_AMOUNT_DECIMAL_PLACES,
        )

    # Determine the final linkage action, then lock exactly the Account
    # row(s) that action requires - never more, never fewer.
    if current_account_id is None and final_account_id is None:
        link_action = "none"
    elif current_account_id is not None and final_account_id is None:
        link_action = "detach"
    elif current_account_id is None and final_account_id is not None:
        link_action = "attach"
    elif current_account_id == final_account_id:
        link_action = "stay"
    else:
        link_action = "move"

    projection_touch_needed = link_action in ("attach", "detach", "move") or (
        link_action == "stay" and monetary_fields_changed
    )

    old_account: Optional[AccountModel] = None
    new_account: Optional[AccountModel] = None

    if projection_touch_needed:
        if link_action == "detach":
            old_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=current_account_id, user_id=user_id,
            )

        elif link_action == "attach":
            new_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=final_account_id, user_id=user_id,
            )
            _validate_income_account_link(new_account, final_currency)

        elif link_action == "stay":
            new_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=final_account_id, user_id=user_id,
            )
            _validate_income_currency_matches_account(new_account, final_currency)

        else:  # move
            if current_account_id < final_account_id:
                first_id, second_id = current_account_id, final_account_id
            else:
                first_id, second_id = final_account_id, current_account_id

            first_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=first_id, user_id=user_id,
            )
            second_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=second_id, user_id=user_id,
            )
            old_account = (
                first_account if first_account.id == current_account_id else second_account
            )
            new_account = (
                first_account if first_account.id == final_account_id else second_account
            )

            # Moving OUT of an archived Account is allowed; moving INTO
            # one is new activity against the destination and is not.
            _validate_income_account_link(new_account, final_currency)

    income_model = income_repository.update_income(
        db_session=db_session,
        income_model=income_model,
        income_data=income_data,
        base_amount=resolved_base_amount,
        base_currency=resolved_base_currency,
        fx_rate=resolved_fx_rate,
        fx_rate_date=resolved_fx_rate_date,
        fx_source=resolved_fx_source,
        commit=False,
    )

    if link_action == "detach":
        account_transaction_repository.delete_income_projection(
            db_session=db_session, projection=current_projection, commit=False,
        )
    elif link_action == "attach":
        account_transaction_repository.create_income_projection(
            db_session=db_session,
            account_id=new_account.id,
            income_id=income_model.id,
            user_id=user_id,
            amount=final_amount,
            transaction_date=final_received_at,
            commit=False,
        )
    elif projection_touch_needed:  # "stay" or "move" with a real sync to do
        account_transaction_repository.update_income_projection(
            db_session=db_session,
            projection=current_projection,
            account_id=new_account.id if link_action == "move" else None,
            amount=final_amount,
            transaction_date=final_received_at,
            commit=False,
        )

    db_session.commit()
    db_session.refresh(income_model)

    return _build_income_response(income_model, account_id=final_account_id)


# Deletes an existing income record owned by the authenticated user,
# leaving Account balances correct.
# This function exists to keep delete business flow in the service layer.
# Locking order (VF-017D): lock Income first, resolve its current
# projection while Income is locked, then lock the linked Account (if
# any) so this delete is correctly serialized against concurrent
# Account-side operations. The AccountTransaction projection itself is
# never explicitly deleted here - it is removed by the database via
# ON DELETE CASCADE (income_id -> income.id) as part of the same DELETE
# statement/transaction that removes the Income row, once the Account
# lock above has already been acquired. Explicitly deleting the
# projection first would merely duplicate what CASCADE already does,
# without the lock-ordering guarantee CASCADE alone cannot provide (a
# bare CASCADE never goes through get_account_by_id_for_update).
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
    income_model = income_repository.get_income_by_id_for_update(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    current_projection = account_transaction_repository.get_income_projection(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    if current_projection is not None:
        account_repository.get_account_by_id_for_update(
            db_session=db_session,
            account_id=current_projection.account_id,
            user_id=user_id,
        )

    income_repository.delete_income(
        db_session=db_session,
        income_model=income_model,
        commit=False,
    )

    db_session.commit()
