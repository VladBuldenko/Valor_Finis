from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.modules.categories import service as categories_service
from sqlalchemy.orm import Session

from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_errors import AccountArchivedError
from app.modules.accounts.account_models import AccountModel
from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_errors import ExpenseAccountCurrencyMismatchError
from app.modules.expenses.expenses_models import ExpenseModel
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


# Validates that an Account can receive a NEW linked-Expense relationship
# (create, attach, or move-in). Exact mirror of
# income_service._validate_income_account_link.
# This function exists for the two cases where linking adds activity to
# the destination Account - an archived Account must never gain a new
# debit. It must never be used for the "stays linked to the same
# Account" case, where the Account's archived status is irrelevant (see
# _validate_expense_currency_matches_account below) and for the
# "move-out" side of a move, which has no validation at all (VF-017E:
# archived status only ever blocks the destination of new activity,
# never a source being corrected/vacated).
# Parameters:
# - account_model: the target Account, already locked by the caller.
# - expense_currency: the Expense's own (final) currency code.
# Returns:
# - None.
# Raises:
# - AccountArchivedError: the target Account is archived.
# - ExpenseAccountCurrencyMismatchError: currencies do not match exactly.
def _validate_expense_account_link(
    account_model: AccountModel,
    expense_currency: str,
) -> None:
    if account_model.status == "archived":
        raise AccountArchivedError()

    _validate_expense_currency_matches_account(account_model, expense_currency)


# Validates only that an Expense's currency matches an Account's
# currency, with no archived-status check. Exact mirror of
# income_service._validate_income_currency_matches_account.
# This function exists for the "stays linked to the same Account" case:
# correcting/synchronizing an Expense that is already linked is never
# blocked by that Account having been archived afterward (VF-017E) -
# only a currency mismatch is ever rejected there.
# Parameters:
# - account_model: the Account the Expense remains linked to.
# - expense_currency: the Expense's own (final) currency code.
# Returns:
# - None.
# Raises:
# - ExpenseAccountCurrencyMismatchError: currencies do not match exactly.
def _validate_expense_currency_matches_account(
    account_model: AccountModel,
    expense_currency: str,
) -> None:
    if expense_currency != account_model.currency:
        raise ExpenseAccountCurrencyMismatchError()


# Builds an ExpenseResponse from an Expense model and an already-resolved
# account_id. Exact mirror of income_service._build_income_response.
# This function exists because ExpenseResponse.model_validate(expense_model)
# is no longer sufficient on its own (VF-017E): account_id has no
# database column to read via ORM attribute access at all - it must
# always be supplied explicitly, by a caller that has already resolved it
# (a single lookup for create/update, or a bulk-resolved mapping for
# get_expenses). This is the only function in this module that
# constructs an ExpenseResponse, so there is exactly one place
# account_id's source can ever be wrong.
# Parameters:
# - expense_model: the Expense database record.
# - account_id: the Account this Expense is currently linked to, or None.
# Returns:
# - ExpenseResponse with account_id set to the given, already-derived
#   value.
def _build_expense_response(
    expense_model: ExpenseModel,
    account_id: Optional[UUID],
) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense_model.id,
        user_id=expense_model.user_id,
        category_id=expense_model.category_id,
        title=expense_model.title,
        amount=expense_model.amount,
        currency=expense_model.currency,
        expense_date=expense_model.expense_date,
        description=expense_model.description,
        source=expense_model.source,
        account_id=account_id,
        base_amount=expense_model.base_amount,
        base_currency=expense_model.base_currency,
        fx_rate=expense_model.fx_rate,
        fx_rate_date=expense_model.fx_rate_date,
        fx_source=expense_model.fx_source,
        created_at=expense_model.created_at,
        updated_at=expense_model.updated_at,
    )


# Creates a new expense using validated expense data and authenticated
# user id, optionally linking it to an Account atomically.
# This function exists to keep business logic separate from API and
# database layers.
# Resolves the VF-014B5C FX snapshot before persisting anything: the
# user's base currency (VF-014B5B), then a historical rate for
# expense_date, then base_amount - all before the expense row is
# constructed at all, so a provider failure leaves no Expense row
# created. This is also, deliberately, before any Account row is locked
# (VF-017E): FX resolution can perform real network I/O (ECB/NBU), and an
# Account SELECT ... FOR UPDATE lock must never be held across a network
# call - identical rule to income_service.create_income. For an unlinked
# create this is the entire operation, unchanged from before VF-017E. For
# a linked create: lock the target Account, validate it (owned by this
# user, not archived, exact currency match against Expense.currency -
# never base_currency/base_amount), insert the Expense, insert its
# AccountTransaction projection, one commit - if validation fails,
# neither row is written.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data, optionally including
#   account_id.
# - user_id: authenticated user identifier that owns the expense.
# - commit: whether the expense should be committed immediately.
# Returns:
# - ExpenseResponse object created from the saved database model, with
#   account_id reflecting the (possibly newly-created) linkage.
# Raises:
# - CategoryNotFoundError: when category_id is set and the category does
#   not exist or does not belong to the authenticated user.
# - AccountNotFoundError: account_id does not exist or is not owned by
#   this user.
# - AccountArchivedError: account_id refers to an archived Account.
# - ExpenseAccountCurrencyMismatchError: the Expense's currency does not
#   exactly match the Account's currency.
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

    if expense_data.account_id is None:
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
        return _build_expense_response(expense_model, account_id=None)

    # Linked create: FX resolution above already happened before any
    # Account lock - now lock the Account and validate before writing
    # anything at all.
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session,
        account_id=expense_data.account_id,
        user_id=user_id,
    )
    _validate_expense_account_link(account_model, expense_data.currency)

    expense_model = expenses_repository.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=stored_fx_rate,
        fx_rate_date=fx_result.actual_rate_date,
        fx_source=fx_result.source,
        commit=False,
    )

    account_transaction_repository.create_expense_projection(
        db_session=db_session,
        account_id=account_model.id,
        expense_id=expense_model.id,
        user_id=user_id,
        amount=expense_model.amount,
        transaction_date=expense_model.expense_date,
        commit=False,
    )

    if commit:
        db_session.commit()
        db_session.refresh(expense_model)

    return _build_expense_response(expense_model, account_id=account_model.id)


# Returns expenses for the authenticated user, each with its
# currently-linked account_id (or None) resolved.
# This function exists to keep response mapping outside the repository
# layer and to ensure service-level reads are always scoped to a user.
# account_id is resolved with exactly one bulk query for the whole list
# (get_expense_account_links_for_user), never one projection lookup per
# Expense (VF-017E) - mirrors income_service.get_income's exact shape.
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

    account_links = account_transaction_repository.get_expense_account_links_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        _build_expense_response(expense_model, account_links.get(expense_model.id))
        for expense_model in expense_models
    ]


# Updates an existing expense owned by the authenticated user, evaluating
# the PATCH against its FINAL state - never field by field in isolation -
# and keeping any Account linkage synchronized atomically.
#
# Locking order (VF-017E, mirrors income_service.update_income exactly):
# the Expense row is locked FIRST (get_expense_by_id_for_update), and its
# current Account projection is resolved only after that lock is held -
# reading "which Account is this currently linked to" before locking
# Expense would be a stale-read TOCTOU window, since that fact is itself
# derived from a projection a concurrent request could change. Only once
# the final linkage state is known are the required Account row(s)
# locked - one Account for attach/detach/stay, two (in ascending UUID
# order, to avoid deadlocking against a concurrent opposite-direction
# move) for a move. If a fresh FX resolution is required, it happens
# BEFORE any Account lock is taken, for the same
# never-hold-a-lock-across-network-I/O reason as create_expense. No
# Account is locked at all when the Expense stays unlinked and no
# monetary field is changing (a pure metadata edit never touches this
# domain) - this is also exactly why a pure account_id-only PATCH (attach/
# detach/move with no amount/currency/expense_date change) never calls
# the FX provider: account_id is deliberately not a member of the
# monetary-fields set below.
#
# VF-014B5C FX snapshot rule (unchanged from before VF-017E):
# - non-monetary fields only (category_id/title/description/source/
#   account_id): snapshot copied unchanged, no provider call.
# - amount changed, currency/expense_date unchanged, and a real snapshot
#   already exists: reuse the stored fx_rate/fx_rate_date/fx_source,
#   only recompute base_amount from the new amount.
# - currency and/or expense_date changed, OR this is a legacy unresolved
#   expense (no snapshot yet) now receiving a monetary update: resolve a
#   full snapshot exactly once, using the final amount/currency/date.
#
# Archived-Account rule (VF-017E, mirrors VF-017D): rejected only when
# the operation adds NEW activity to an Account - attaching, or moving
# INTO an archived Account. Never rejected for amount/date corrections to
# an Expense already linked to an Account that was archived afterward,
# and never rejected for detaching or moving OUT of an archived Account -
# those are corrections/removals of existing history, not new activity.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - expense_data: validated partial expense update data, evaluated as a
#   whole (final state), including any account_id change.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseResponse object created from the updated database model, with
#   account_id reflecting the resulting linkage.
# Raises:
# - ExpenseNotFoundError: when the expense does not exist or does not
#   belong to the user.
# - CategoryNotFoundError: when category_id is being changed to a
#   non-null value and the category does not exist or does not belong to
#   the authenticated user.
# - AccountNotFoundError: a referenced account_id does not exist or is
#   not owned by this user.
# - AccountArchivedError: new activity (attach/move-in) targets an
#   archived Account.
# - ExpenseAccountCurrencyMismatchError: the final currency does not
#   exactly match the final linked Account's currency.
# - FxFutureDatedNotSupportedError/FxRateUnavailableError/
#   FxProviderUnavailableError: see create_expense - only raised when a
#   monetary field actually changed and a fresh resolution was required.
def update_expense(
    db_session: Session,
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    user_id: UUID,
) -> ExpenseResponse:
    expense_model = expenses_repository.get_expense_by_id_for_update(
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

    current_projection = account_transaction_repository.get_expense_projection(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )
    current_account_id = current_projection.account_id if current_projection else None

    fields_set = expense_data.model_fields_set
    final_account_id = (
        expense_data.account_id if "account_id" in fields_set else current_account_id
    )

    monetary_fields_changed = bool({"amount", "currency", "expense_date"} & fields_set)

    final_currency = (
        expense_data.currency if "currency" in fields_set else expense_model.currency
    )
    final_expense_date = (
        expense_data.expense_date
        if "expense_date" in fields_set
        else expense_model.expense_date
    )
    final_amount = (
        expense_data.amount if "amount" in fields_set else expense_model.amount
    )

    # FX resolution (if needed) happens before any Account lock is taken.
    if not monetary_fields_changed:
        # Metadata-only update: the snapshot (resolved or unresolved) is
        # left exactly as it was - never forces a network call.
        resolved_base_amount = expense_model.base_amount
        resolved_base_currency = expense_model.base_currency
        resolved_fx_rate = expense_model.fx_rate
        resolved_fx_rate_date = expense_model.fx_rate_date
        resolved_fx_source = expense_model.fx_source
    else:
        currency_or_date_changed = (
            final_currency != expense_model.currency
            or final_expense_date != expense_model.expense_date
        )

        if not currency_or_date_changed and expense_model.base_amount is not None:
            # amount-only change against an already-resolved snapshot:
            # reuse the stored rate, never re-fetch.
            resolved_base_currency = expense_model.base_currency
            resolved_fx_rate = expense_model.fx_rate
            resolved_fx_rate_date = expense_model.fx_rate_date
            resolved_fx_source = expense_model.fx_source
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
            _validate_expense_account_link(new_account, final_currency)

        elif link_action == "stay":
            new_account = account_repository.get_account_by_id_for_update(
                db_session=db_session, account_id=final_account_id, user_id=user_id,
            )
            _validate_expense_currency_matches_account(new_account, final_currency)

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
            _validate_expense_account_link(new_account, final_currency)

    expense_model = expenses_repository.update_expense(
        db_session=db_session,
        expense_model=expense_model,
        expense_data=expense_data,
        base_amount=resolved_base_amount,
        base_currency=resolved_base_currency,
        fx_rate=resolved_fx_rate,
        fx_rate_date=resolved_fx_rate_date,
        fx_source=resolved_fx_source,
        commit=False,
    )

    if link_action == "detach":
        account_transaction_repository.delete_expense_projection(
            db_session=db_session, projection=current_projection, commit=False,
        )
    elif link_action == "attach":
        account_transaction_repository.create_expense_projection(
            db_session=db_session,
            account_id=new_account.id,
            expense_id=expense_model.id,
            user_id=user_id,
            amount=final_amount,
            transaction_date=final_expense_date,
            commit=False,
        )
    elif projection_touch_needed:  # "stay" or "move" with a real sync to do
        account_transaction_repository.update_expense_projection(
            db_session=db_session,
            projection=current_projection,
            account_id=new_account.id if link_action == "move" else None,
            amount=final_amount,
            transaction_date=final_expense_date,
            commit=False,
        )

    db_session.commit()
    db_session.refresh(expense_model)

    return _build_expense_response(expense_model, account_id=final_account_id)


# Deletes an existing expense owned by the authenticated user, leaving
# Account balances correct.
# This function exists to keep delete business flow in the service layer.
# Locking order (VF-017E, mirrors income_service.delete_income exactly):
# lock Expense first, resolve its current projection while Expense is
# locked, then lock the linked Account (if any) so this delete is
# correctly serialized against concurrent Account-side operations. The
# AccountTransaction projection itself is never explicitly deleted here -
# it is removed by the database via ON DELETE CASCADE (expense_id ->
# expenses.id) as part of the same DELETE statement/transaction that
# removes the Expense row, once the Account lock above has already been
# acquired. Explicitly deleting the projection first would merely
# duplicate what CASCADE already does, without the lock-ordering
# guarantee CASCADE alone cannot provide (a bare CASCADE never goes
# through get_account_by_id_for_update). Receipt's own, entirely
# independent expense_id -> expenses.id ON DELETE SET NULL FK fires from
# this same DELETE with no ordering conflict and needs no code here at
# all.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - None.
# Raises:
# - ExpenseNotFoundError: when the expense does not exist or does not
#   belong to the user.
def delete_expense(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> None:
    expense_model = expenses_repository.get_expense_by_id_for_update(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    current_projection = account_transaction_repository.get_expense_projection(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    if current_projection is not None:
        account_repository.get_account_by_id_for_update(
            db_session=db_session,
            account_id=current_projection.account_id,
            user_id=user_id,
        )

    expenses_repository.delete_expense(
        db_session=db_session,
        expense_model=expense_model,
        commit=False,
    )

    db_session.commit()
