import threading
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service, account_transaction_repository
from app.modules.accounts.account_errors import AccountArchivedError, AccountNotFoundError
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.income import income_repository, income_service
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate, IncomeUpdate


def _create_account(db_session, user_id, name="Checking") -> AccountModel:
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
        user_id=user_id,
    )


def _create_unlinked_income(db_session, user_id, amount=Decimal("100.00")) -> IncomeModel:
    result = income_service.create_income(
        db_session=db_session,
        income_data=IncomeCreate(
            amount=amount, currency="EUR", received_at=date(2026, 9, 1), source="salary",
        ),
        user_id=user_id,
    )
    return income_repository.get_income_by_id(
        db_session=db_session, income_id=result.id, user_id=user_id,
    )


# Tests the concurrency invariant for archiving an Account vs. a
# concurrent attach of an existing Income to that same Account: the
# Account row lock (already proven for archive-vs-adjustment in VF-017B)
# serializes this identically, since attach is structurally the same
# "lock Account, check status, insert an AccountTransaction row" flow as
# a direct adjustment, just with kind="income" instead of "adjustment".
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if archive always succeeds and attach's
#   outcome is consistent with the observed final state.
def test_concurrent_archive_vs_attach(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(setup_session, user_id)
        account_id = account.id
        income = _create_unlinked_income(setup_session, user_id)
        income_id = income.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_archive() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.update_account(
                db_session=db_session, account_id=account_id,
                account_data=AccountUpdate(status="archived"), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()
        with results_lock:
            results["archive"] = outcome

    def attempt_attach() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            income_service.update_income(
                db_session=db_session, income_id=income_id,
                income_data=IncomeUpdate(account_id=account_id), user_id=user_id,
            )
            outcome = "succeeded"
        except AccountArchivedError:
            outcome = "rejected_archived"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()
        with results_lock:
            results["attach"] = outcome

    thread_a = threading.Thread(target=attempt_archive)
    thread_b = threading.Thread(target=attempt_attach)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert results["archive"] == "succeeded"
    assert results["attach"] in ("succeeded", "rejected_archived")

    verify_session = SessionLocal()
    try:
        projection = account_transaction_repository.get_income_projection(
            db_session=verify_session, income_id=income_id, user_id=user_id,
        )
        if results["attach"] == "succeeded":
            assert projection is not None
        else:
            assert projection is None
    finally:
        verify_session.close()


# Tests the concurrency invariant for an Account currency change vs. the
# first linked Income (attach). Unlike VF-017B's currency-change-vs-
# first-adjustment race, attach is NOT guaranteed to always succeed here
# - a direct adjustment never depends on the Account's currency at all,
# but attach's own currency-match validation genuinely does. This test
# therefore checks the two self-consistent outcome pairs, not "attach
# always wins":
# - currency_change wins the lock race (commits first) => the Account's
#   currency has already changed by the time attach re-reads it under
#   its own lock, so attach correctly fails with a currency mismatch
#   (the Income stayed EUR, the Account became USD).
# - attach wins the lock race (commits first, establishing history)
#   => currency_change is then blocked by has_transactions_for_account
#   exactly as it would be for a direct adjustment (this half IS
#   identical to VF-017B's proven behavior).
# Either way, no corrupted/inconsistent state (e.g. a currency change
# succeeding while an income-backed row from the old currency silently
# remains) is ever produced.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one of the two legitimate outcome
#   pairs holds and the final database state matches it.
def test_concurrent_currency_change_vs_first_attach(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(setup_session, user_id)
        account_id = account.id
        income = _create_unlinked_income(setup_session, user_id)
        income_id = income.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_currency_change() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.update_account(
                db_session=db_session, account_id=account_id,
                account_data=AccountUpdate(currency="USD"), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "rejected"
        finally:
            db_session.close()
        with results_lock:
            results["currency_change"] = outcome

    def attempt_attach() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            income_service.update_income(
                db_session=db_session, income_id=income_id,
                income_data=IncomeUpdate(account_id=account_id), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "failed"
        finally:
            db_session.close()
        with results_lock:
            results["attach"] = outcome

    thread_a = threading.Thread(target=attempt_currency_change)
    thread_b = threading.Thread(target=attempt_attach)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    outcome_pair = (results["currency_change"], results["attach"])
    assert outcome_pair in [
        ("succeeded", "failed"),
        ("rejected", "succeeded"),
    ], outcome_pair

    verify_session = SessionLocal()
    try:
        final_account = (
            verify_session.query(AccountModel).filter(AccountModel.id == account_id).first()
        )

        if outcome_pair == ("succeeded", "failed"):
            assert final_account.currency == "USD"
            assert account_transaction_repository.get_income_projection(
                db_session=verify_session, income_id=income_id, user_id=user_id,
            ) is None
        else:
            assert final_account.currency == "EUR"
            assert account_transaction_repository.has_transactions_for_account(
                db_session=verify_session, account_id=account_id, user_id=user_id,
            )
    finally:
        verify_session.close()


# Tests the concurrency invariant for deleting an Account vs. a
# concurrent attach of an Income to it: the Account row lock serializes
# this identically to any other lifecycle race - whichever operation
# locks the Account row first determines the outcome for the other.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one of the two legitimate outcome
#   pairs holds.
def test_concurrent_account_delete_vs_attach(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(setup_session, user_id)
        account_id = account.id
        income = _create_unlinked_income(setup_session, user_id)
        income_id = income.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_delete() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.delete_account(
                db_session=db_session, account_id=account_id, user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "rejected_has_history"
        finally:
            db_session.close()
        with results_lock:
            results["delete"] = outcome

    def attempt_attach() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            income_service.update_income(
                db_session=db_session, income_id=income_id,
                income_data=IncomeUpdate(account_id=account_id), user_id=user_id,
            )
            outcome = "succeeded"
        except AccountNotFoundError:
            outcome = "not_found"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()
        with results_lock:
            results["attach"] = outcome

    thread_a = threading.Thread(target=attempt_delete)
    thread_b = threading.Thread(target=attempt_attach)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    outcome_pair = (results["delete"], results["attach"])
    assert outcome_pair in [
        ("succeeded", "not_found"),
        ("rejected_has_history", "succeeded"),
    ], outcome_pair


# Tests that two simultaneous updates to the SAME linked Income (both
# changing amount) both succeed with no lost update - the Income row
# lock (a genuinely new requirement introduced by VF-017D; update_income
# had no row lock before this slice) correctly serializes them.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both updates succeed and the projection's
#   final amount matches whichever update's value actually persisted
#   last, not a corrupted/partial value.
def test_concurrent_updates_to_same_linked_income(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(setup_session, user_id)
        account_id = account.id
        result = income_service.create_income(
            db_session=setup_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_id,
            ),
            user_id=user_id,
        )
        income_id = result.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_update(thread_name: str, amount: Decimal) -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            income_service.update_income(
                db_session=db_session, income_id=income_id,
                income_data=IncomeUpdate(amount=amount), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()
        with results_lock:
            results[thread_name] = outcome

    thread_a = threading.Thread(target=attempt_update, args=("a", Decimal("200.00")))
    thread_b = threading.Thread(target=attempt_update, args=("b", Decimal("300.00")))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert results["a"] == "succeeded"
    assert results["b"] == "succeeded"

    verify_session = SessionLocal()
    try:
        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session, account_id=account_id, user_id=user_id,
        )
        # Whichever update committed last "wins" (standard last-write-wins
        # semantics under a serializing row lock, not a lost/partial
        # update) - the final balance must exactly equal ONE of the two
        # attempted amounts, never a corrupted third value.
        assert balance in (Decimal("200.00"), Decimal("300.00"))

        income_model = (
            verify_session.query(IncomeModel).filter(IncomeModel.id == income_id).first()
        )
        assert income_model.amount == balance
    finally:
        verify_session.close()


# Tests that concurrent opposite-direction moves of two different Incomes
# between the same two Accounts never deadlock, thanks to the ascending-
# UUID lock ordering rule.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both moves complete (neither thread times
#   out/deadlocks) and the final balances are exactly consistent with
#   whichever outcomes occurred.
def test_concurrent_opposite_direction_moves_do_not_deadlock(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account_x = _create_account(setup_session, user_id, name="X")
        account_y = _create_account(setup_session, user_id, name="Y")

        income_1 = income_service.create_income(
            db_session=setup_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_x.id,
            ),
            user_id=user_id,
        )
        income_2 = income_service.create_income(
            db_session=setup_session,
            income_data=IncomeCreate(
                amount=Decimal("50.00"), currency="EUR",
                received_at=date(2026, 9, 2), source="gift", account_id=account_y.id,
            ),
            user_id=user_id,
        )
        account_x_id, account_y_id = account_x.id, account_y.id
        income_1_id, income_2_id = income_1.id, income_2.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def move(thread_name: str, income_id, target_account_id) -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            income_service.update_income(
                db_session=db_session, income_id=income_id,
                income_data=IncomeUpdate(account_id=target_account_id), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()
        with results_lock:
            results[thread_name] = outcome

    # Income 1 moves X -> Y, Income 2 moves Y -> X: opposite directions
    # across the same two Accounts.
    thread_a = threading.Thread(target=move, args=("a", income_1_id, account_y_id))
    thread_b = threading.Thread(target=move, args=("b", income_2_id, account_x_id))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert results["a"] == "succeeded"
    assert results["b"] == "succeeded"

    verify_session = SessionLocal()
    try:
        balance_x = account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session, account_id=account_x_id, user_id=user_id,
        )
        balance_y = account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session, account_id=account_y_id, user_id=user_id,
        )
        # Income 1 (100) ended on Y, Income 2 (50) ended on X.
        assert balance_x == Decimal("50.00")
        assert balance_y == Decimal("100.00")
    finally:
        verify_session.close()
