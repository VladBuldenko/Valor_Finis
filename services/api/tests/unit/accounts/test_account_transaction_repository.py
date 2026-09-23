from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_schemas import AccountCreate


def _create_account(db_session, user_id, name="Main Checking"):
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
        user_id=user_id,
    )


def _add_transaction(db_session, account_id, user_id, kind, direction, amount, transaction_date):
    return account_transaction_repository.create_transaction(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
        kind=kind,
        direction=direction,
        amount=amount,
        transaction_date=transaction_date,
        description=None,
    )


# Tests that a new account with no transactions has a ledger balance of
# exactly 0.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the balance is Decimal("0.00").
def test_calculate_ledger_balance_zero_when_no_transactions(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that credit transactions increase the balance and debit
# transactions decrease it, computed exactly with Decimal.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the final balance is the exact signed sum.
def test_calculate_ledger_balance_mixed_credit_and_debit(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        _add_transaction(
            db_session, account.id, user_id, "opening_balance", "credit",
            Decimal("100.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, account.id, user_id, "adjustment", "debit",
            Decimal("30.00"), date(2026, 9, 2),
        )
        _add_transaction(
            db_session, account.id, user_id, "adjustment", "credit",
            Decimal("5.50"), date(2026, 9, 3),
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("75.50")
    finally:
        db_session.close()


# Tests that a debit larger than accumulated credits produces a negative
# ledger balance.
# This test exists to prove the ledger calculation itself has no floor -
# unlike Goal, an Account balance may legitimately be negative.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the balance is exactly -25.00.
def test_calculate_ledger_balance_may_be_negative(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        _add_transaction(
            db_session, account.id, user_id, "opening_balance", "credit",
            Decimal("50.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, account.id, user_id, "adjustment", "debit",
            Decimal("75.00"), date(2026, 9, 2),
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-25.00")
    finally:
        db_session.close()


# Tests that transaction history is returned newest first, deterministically
# ordered by transaction_date, then created_at, then id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the most recently dated transaction is first.
def test_get_transactions_for_account_orders_newest_first(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        first = _add_transaction(
            db_session, account.id, user_id, "opening_balance", "credit",
            Decimal("100.00"), date(2026, 9, 1),
        )
        second = _add_transaction(
            db_session, account.id, user_id, "adjustment", "credit",
            Decimal("10.00"), date(2026, 9, 5),
        )

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )

        assert [t.id for t in history] == [second.id, first.id]
    finally:
        db_session.close()


# Tests that get_ledger_balances_for_user computes correct balances for
# multiple accounts in a single bulk grouped query.
# This test exists to prove the N+1-safe bulk-balance pattern (mirroring
# Goal's get_ledger_balances_for_user) works correctly for Accounts too.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both accounts' balances are correct and a
#   third, untouched account is simply absent from the mapping.
def test_get_ledger_balances_for_user_bulk_correct(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        funded_account = _create_account(db_session, user_id, name="Funded")
        overdrawn_account = _create_account(db_session, user_id, name="Overdrawn")
        untouched_account = _create_account(db_session, user_id, name="Untouched")

        _add_transaction(
            db_session, funded_account.id, user_id, "opening_balance", "credit",
            Decimal("200.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, overdrawn_account.id, user_id, "opening_balance", "credit",
            Decimal("10.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, overdrawn_account.id, user_id, "adjustment", "debit",
            Decimal("40.00"), date(2026, 9, 2),
        )

        balances = account_transaction_repository.get_ledger_balances_for_user(
            db_session=db_session, user_id=user_id,
        )

        assert balances[funded_account.id] == Decimal("200.00")
        assert balances[overdrawn_account.id] == Decimal("-30.00")
        assert untouched_account.id not in balances
    finally:
        db_session.close()


# Tests that another user's account transactions never leak into this
# user's bulk balance mapping.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's account appears.
def test_get_ledger_balances_for_user_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        other_account = _create_account(db_session, other_user_id)

        _add_transaction(
            db_session, account.id, user_id, "opening_balance", "credit",
            Decimal("10.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, other_account.id, other_user_id, "opening_balance", "credit",
            Decimal("9999.00"), date(2026, 9, 1),
        )

        balances = account_transaction_repository.get_ledger_balances_for_user(
            db_session=db_session, user_id=user_id,
        )

        assert balances == {account.id: Decimal("10.00")}
    finally:
        db_session.close()


# Tests that has_transactions_for_account returns False when no
# transactions exist.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_account returns False.
def test_has_transactions_for_account_false_when_none(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        assert account_transaction_repository.has_transactions_for_account(
            db_session=db_session, account_id=account.id, user_id=user_id,
        ) is False
    finally:
        db_session.close()


# Tests that has_transactions_for_account returns True even when the
# ledger balance nets to zero.
# This test exists to prove balance is never used as a proxy for history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_account returns True
#   despite a 0.00 balance.
def test_has_transactions_for_account_true_for_zero_balance_history(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        _add_transaction(
            db_session, account.id, user_id, "opening_balance", "credit",
            Decimal("50.00"), date(2026, 9, 1),
        )
        _add_transaction(
            db_session, account.id, user_id, "adjustment", "debit",
            Decimal("50.00"), date(2026, 9, 2),
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")

        assert account_transaction_repository.has_transactions_for_account(
            db_session=db_session, account_id=account.id, user_id=user_id,
        ) is True
    finally:
        db_session.close()
