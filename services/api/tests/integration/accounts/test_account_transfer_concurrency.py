import threading
import time
from datetime import date
from decimal import Decimal
from typing import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_service,
    account_transaction_repository,
    account_transfer_repository,
    account_transfer_service,
)
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
    AccountReferencedByPlannedTransferError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_errors import (
    AccountTransferAlreadyPostedError,
    AccountTransferCurrencyMismatchError,
    AccountTransferIdempotencyConflictError,
    AccountTransferNotFoundError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import (
    AccountTransferCreate,
    AccountTransferPost,
)
from app.modules.income import income_service
from app.modules.income.income_schemas import IncomeCreate, IncomeUpdate

# Real-thread concurrency tests for VF-018C (create/delete/Account
# lifecycle). Each thread uses its own Session/connection; a Barrier
# releases them at the same instant. Every outcome is mapped to a label, and
# any unexpected exception (including a PostgreSQL deadlock, which surfaces
# as OperationalError) becomes "error:<type>", which no test accepts.
# VF-018D adds the manual posting cases. Where a test needs one specific
# serialization, _run_first_then_second forces it with an Event instead of
# relying on scheduling; barrier-only tests assert every legal outcome and
# never claim which one occurred.

AS_OF = date(2026, 9, 28)
POSTED_DATE = date(2026, 9, 20)
PLANNED_DATE = date(2026, 10, 15)
POSTING_DATE = date(2026, 9, 28)


def _setup_accounts(user_id: UUID, *specs) -> list[UUID]:
    """Creates committed Accounts from (name, currency, opening_balance) specs."""
    db_session = SessionLocal()
    try:
        ids = []
        for name, currency, opening_balance in specs:
            account = account_repository.create_account(
                db_session=db_session,
                account_data=AccountCreate(name=name, type="checking", currency=currency),
                user_id=user_id,
            )
            if opening_balance is not None:
                account_transaction_repository.create_transaction(
                    db_session=db_session,
                    account_id=account.id,
                    user_id=user_id,
                    kind="opening_balance",
                    direction="credit",
                    amount=Decimal(opening_balance),
                    transaction_date=date(2026, 9, 1),
                    description=None,
                )
            ids.append(account.id)
        return ids
    finally:
        db_session.close()


def _request(source_id, destination_id, transfer_date, amount="100.00", key=None):
    return AccountTransferCreate(
        client_request_id=key or uuid4(),
        source_account_id=source_id,
        destination_account_id=destination_id,
        amount=Decimal(amount),
        transfer_date=transfer_date,
    )


def _create(request: AccountTransferCreate, user_id: UUID) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            result = account_transfer_service.create_account_transfer(
                db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
            )
            return "created" if result.created else "replayed"
        except AccountTransferIdempotencyConflictError:
            return "conflict"
        except AccountNotFoundError:
            return "account_not_found"
        except AccountTransferCurrencyMismatchError:
            return "currency_mismatch"
        except AccountArchivedError:
            return "archived"
    return run


def _delete_account(account_id: UUID, user_id: UUID) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            account_service.delete_account(
                db_session=db_session, account_id=account_id, user_id=user_id,
            )
            return "deleted"
        except AccountReferencedByPlannedTransferError:
            return "planned_reference"
        except AccountDeletionNotAllowedError:
            return "history"
    return run


def _update_account(account_id: UUID, user_id: UUID, update: AccountUpdate, label: str):
    def run(db_session: Session) -> str:
        try:
            account_service.update_account(
                db_session=db_session, account_id=account_id,
                account_data=update, user_id=user_id,
            )
            return label
        except AccountReferencedByPlannedTransferError:
            return "planned_reference"
        except AccountCurrencyImmutableError:
            return "history"
    return run


def _delete_transfer(transfer_id: UUID, user_id: UUID) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            account_transfer_service.delete_account_transfer(
                db_session=db_session, transfer_id=transfer_id, user_id=user_id,
            )
            return "deleted"
        except AccountTransferNotFoundError:
            return "transfer_not_found"
    return run


def _run_concurrently(tasks: dict[str, Callable[[Session], str]]) -> dict[str, str]:
    barrier = threading.Barrier(len(tasks))
    results: dict[str, str] = {}
    results_lock = threading.Lock()

    def runner(name: str, task: Callable[[Session], str]) -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            outcome = task(db_session)
        except Exception as error:
            outcome = f"error:{type(error).__name__}"
        finally:
            db_session.close()
        with results_lock:
            results[name] = outcome

    threads = [
        threading.Thread(target=runner, args=item, name=item[0]) for item in tasks.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert set(results) == set(tasks), f"threads did not finish: {results}"
    return results


def _balance(account_id: UUID, user_id: UUID) -> Decimal:
    db_session = SessionLocal()
    try:
        return account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account_id, user_id=user_id,
        )
    finally:
        db_session.close()


def _counts(user_id: UUID) -> tuple:
    db_session = SessionLocal()
    try:
        transfers = db_session.query(AccountTransferModel).filter(
            AccountTransferModel.user_id == user_id,
        ).count()
        legs = db_session.query(AccountTransactionModel).filter(
            AccountTransactionModel.user_id == user_id,
            AccountTransactionModel.kind == "transfer",
        ).count()
        return transfers, legs
    finally:
        db_session.close()


def _account_exists(account_id: UUID) -> bool:
    db_session = SessionLocal()
    try:
        return db_session.get(AccountModel, account_id) is not None
    finally:
        db_session.close()


def _create_committed(request: AccountTransferCreate, user_id: UUID):
    db_session = SessionLocal()
    try:
        return account_transfer_service.create_account_transfer(
            db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
        ).transfer
    finally:
        db_session.close()


def _currency(account_id: UUID) -> str:
    db_session = SessionLocal()
    try:
        return db_session.get(AccountModel, account_id).currency
    finally:
        db_session.close()


def _transfer_state(transfer_id: UUID):
    """Returns (status or None if deleted, sorted leg directions)."""
    db_session = SessionLocal()
    try:
        transfer = db_session.get(AccountTransferModel, transfer_id)
        directions = sorted(
            leg.direction
            for leg in db_session.query(AccountTransactionModel).filter(
                AccountTransactionModel.transfer_id == transfer_id,
            )
        )
        return (transfer.status if transfer is not None else None), directions
    finally:
        db_session.close()


def _post(transfer_id: UUID, user_id: UUID) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            account_transfer_service.post_account_transfer(
                db_session=db_session,
                transfer_id=transfer_id,
                user_id=user_id,
                post_data=AccountTransferPost(effective_date=POSTING_DATE),
            )
            return "posted"
        except AccountTransferAlreadyPostedError:
            return "already_posted"
        except AccountArchivedError:
            return "archived"
        except AccountTransferNotFoundError:
            return "transfer_not_found"
    return run


# Runs two tasks concurrently in a forced order: `second` starts only after
# `first` has returned from lock_module.lock_function_name (i.e. holds that
# row lock), and `first` keeps the lock for hold_seconds so `second`
# genuinely queues behind it. The order is decided by the Event, not by
# timing - the hold only makes the lock contention real.
def _run_first_then_second(monkeypatch, lock_module, lock_function_name, first, second,
                           hold_seconds: float = 0.3) -> dict[str, str]:
    first_name, first_task = first
    second_name, second_task = second
    first_holds_lock = threading.Event()
    real_lock = getattr(lock_module, lock_function_name)

    def lock_and_signal(*args, **kwargs):
        result = real_lock(*args, **kwargs)
        if threading.current_thread().name == first_name and not first_holds_lock.is_set():
            first_holds_lock.set()
            time.sleep(hold_seconds)
        return result

    monkeypatch.setattr(lock_module, lock_function_name, lock_and_signal)

    def second_after_first_holds_lock(db_session: Session) -> str:
        assert first_holds_lock.wait(timeout=10), "first task never took its lock"
        return second_task(db_session)

    return _run_concurrently({
        first_name: first_task,
        second_name: second_after_first_holds_lock,
    })


# Tests case 1: posted transfers A->B and B->A with distinct keys, started
# together repeatedly, never deadlock (both lock min(A, B) first), both
# commit, and the pair's combined balance never changes.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every round creates both transfers.
def test_opposite_direction_posted_creates_do_not_deadlock(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(
        user_id, ("A", "EUR", "1000.00"), ("B", "EUR", "500.00"),
    )
    rounds = 5

    for _ in range(rounds):
        results = _run_concurrently({
            "a_to_b": _create(_request(account_a, account_b, POSTED_DATE, "300.00"), user_id),
            "b_to_a": _create(_request(account_b, account_a, POSTED_DATE, "100.00"), user_id),
        })
        assert results == {"a_to_b": "created", "b_to_a": "created"}

    assert _balance(account_a, user_id) == Decimal("1000.00") - rounds * Decimal("200.00")
    assert _balance(account_b, user_id) == Decimal("500.00") + rounds * Decimal("200.00")
    assert _balance(account_a, user_id) + _balance(account_b, user_id) == Decimal("1500.00")
    assert _counts(user_id) == (2 * rounds, 4 * rounds)


# Tests case 2: two identical posted create requests with the same key at
# the same time produce exactly one logical transfer - one "created" (201)
# and one "replayed" (200) - and exactly two projection rows.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if there is one transfer with two projections.
def test_same_key_same_payload_creates_one_transfer(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", "1000.00"), ("B", "EUR", None))
    request = _request(account_a, account_b, POSTED_DATE, "300.00")

    results = _run_concurrently({
        "first": _create(request, user_id),
        "second": _create(request, user_id),
    })

    assert sorted(results.values()) == ["created", "replayed"]
    assert _counts(user_id) == (1, 2)
    assert _balance(account_a, user_id) == Decimal("700.00")
    assert _balance(account_b, user_id) == Decimal("300.00")


# Tests case 3: the same key used concurrently for two different,
# non-overlapping Account pairs - which share no Account lock - resolves to
# one created transfer and one idempotency conflict, never a second
# transfer or an unexpected error.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one transfer exists.
def test_same_key_different_account_pairs_one_created_one_conflict(
    clean_database: None,
) -> None:
    user_id = uuid4()
    account_a, account_b, account_c, account_d = _setup_accounts(
        user_id, ("A", "EUR", None), ("B", "EUR", None), ("C", "EUR", None), ("D", "EUR", None),
    )
    key = uuid4()

    results = _run_concurrently({
        "a_to_b": _create(_request(account_a, account_b, POSTED_DATE, key=key), user_id),
        "c_to_d": _create(_request(account_c, account_d, POSTED_DATE, key=key), user_id),
    })

    assert sorted(results.values()) == ["conflict", "created"]
    assert _counts(user_id) == (1, 2)


# Tests case 4: an exact replay racing an archive of one of the transfer's
# Accounts always resolves as a replay - Account validation never reruns
# for an existing logical transfer - and the archive succeeds.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay and the archive both succeed.
def test_exact_replay_vs_account_archive(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    request = _request(account_a, account_b, PLANNED_DATE)
    original = _create_committed(request, user_id)

    results = _run_concurrently({
        "replay": _create(request, user_id),
        "archive": _update_account(account_a, user_id, AccountUpdate(status="archived"), "archived_ok"),
    })

    assert results == {"replay": "replayed", "archive": "archived_ok"}
    assert _counts(user_id) == (1, 0)
    assert original.status == "planned"


# Tests case 5: creating a planned transfer to a fresh Account while that
# Account is being deleted serializes cleanly: either the plan commits
# first and the delete is refused (409 planned reference), or the delete
# commits first and the create finds no Account (404) - never an
# unexpected error.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the outcome pair and final state agree.
def test_planned_create_vs_account_delete(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_d = _setup_accounts(user_id, ("A", "EUR", None), ("D", "EUR", None))

    results = _run_concurrently({
        "create": _create(_request(account_a, account_d, PLANNED_DATE), user_id),
        "delete": _delete_account(account_d, user_id),
    })

    assert (results["create"], results["delete"]) in {
        ("created", "planned_reference"),
        ("account_not_found", "deleted"),
    }, results
    if results["create"] == "created":
        assert _account_exists(account_d)
        assert _counts(user_id) == (1, 0)
    else:
        assert not _account_exists(account_d)
        assert _counts(user_id) == (0, 0)


# Tests case 6: creating a planned transfer while one of its fresh EUR
# Accounts is changed to USD (the other stays EUR, so the change creates a
# real mismatch) serializes cleanly: either the plan wins and the currency
# change is refused (409), or the change wins and the create sees a
# currency mismatch (422) - never an unexpected error.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the outcome pair is one of the two legal ones.
def test_planned_create_vs_account_currency_change(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))

    results = _run_concurrently({
        "create": _create(_request(account_a, account_b, PLANNED_DATE), user_id),
        "currency": _update_account(account_a, user_id, AccountUpdate(currency="USD"), "changed"),
    })

    assert (results["create"], results["currency"]) in {
        ("created", "planned_reference"),
        ("currency_mismatch", "changed"),
    }, results
    expected_counts = (1, 0) if results["create"] == "created" else (0, 0)
    assert _counts(user_id) == expected_counts
    assert _currency(account_a) == ("EUR" if results["create"] == "created" else "USD")
    assert _currency(account_b) == "EUR"


# Tests case 7: deleting a planned transfer while deleting its destination
# Account always removes the transfer, and the Account is either deleted
# (the transfer delete committed first) or refused with 409 (the Account
# delete saw the still-existing plan) - never a dangling reference or an
# unexpected error.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the final state is consistent with the outcomes.
def test_planned_transfer_delete_vs_account_delete(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_d = _setup_accounts(user_id, ("A", "EUR", None), ("D", "EUR", None))
    transfer = _create_committed(_request(account_a, account_d, PLANNED_DATE), user_id)

    results = _run_concurrently({
        "delete_transfer": _delete_transfer(transfer.id, user_id),
        "delete_account": _delete_account(account_d, user_id),
    })

    assert results["delete_transfer"] == "deleted", results
    assert results["delete_account"] in {"deleted", "planned_reference"}, results
    assert _counts(user_id) == (0, 0)
    assert _account_exists(account_d) == (results["delete_account"] == "planned_reference")


# Tests case 5 with a FORCED order (VF-018C review follow-up): the planned
# create holds both Account locks first, so the concurrent Account delete
# queues behind it and must then see the committed plan and return 409 -
# the branch the barrier-only test above rarely observes.
# Parameters:
# - monkeypatch: pytest fixture used to force the order.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the plan exists and the Account survives.
def test_planned_create_first_then_account_delete_is_refused(
    monkeypatch, clean_database: None,
) -> None:
    user_id = uuid4()
    account_a, account_d = _setup_accounts(user_id, ("A", "EUR", None), ("D", "EUR", None))

    results = _run_first_then_second(
        monkeypatch, account_repository, "get_accounts_by_ids_for_update",
        ("create", _create(_request(account_a, account_d, PLANNED_DATE), user_id)),
        ("delete", _delete_account(account_d, user_id)),
    )

    assert results == {"create": "created", "delete": "planned_reference"}
    assert _account_exists(account_d)
    assert _counts(user_id) == (1, 0)


# Tests case 6 with a FORCED order (VF-018C review follow-up): the planned
# create commits first, so the queued currency change sees the plan and is
# refused - both Accounts keep EUR.
# Parameters:
# - monkeypatch: pytest fixture used to force the order.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the plan exists and no currency changed.
def test_planned_create_first_then_currency_change_is_refused(
    monkeypatch, clean_database: None,
) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))

    results = _run_first_then_second(
        monkeypatch, account_repository, "get_accounts_by_ids_for_update",
        ("create", _create(_request(account_a, account_b, PLANNED_DATE), user_id)),
        ("currency", _update_account(account_a, user_id, AccountUpdate(currency="USD"), "changed")),
    )

    assert results == {"create": "created", "currency": "planned_reference"}
    assert _counts(user_id) == (1, 0)
    assert (_currency(account_a), _currency(account_b)) == ("EUR", "EUR")


# ------------------------------------------------ VF-018D manual posting


# Tests P1: two concurrent posts of the same planned transfer serialize on
# the transfer row lock - exactly one succeeds, the other is 409 - and the
# transfer ends up posted with exactly one debit and one credit.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if one post wins and there are exactly two rows.
def test_post_vs_post_posts_exactly_once(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", "1000.00"), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE, "300.00"), user_id)

    results = _run_concurrently({
        "first": _post(transfer.id, user_id),
        "second": _post(transfer.id, user_id),
    })

    assert sorted(results.values()) == ["already_posted", "posted"]
    assert _transfer_state(transfer.id) == ("posted", ["credit", "debit"])
    assert _balance(account_a, user_id) == Decimal("700.00")
    assert _balance(account_b, user_id) == Decimal("300.00")


# Tests P2 in both forced orders: post and delete of the same planned
# transfer both lock the transfer first. If the post commits first, the
# delete then removes the transfer and both projections (200 + 204); if the
# delete commits first, the post finds nothing (204 + 404). Either way no
# transfer and no ledger row remain.
# Parameters:
# - post_first: which operation is forced to take the transfer lock first.
# - monkeypatch: pytest fixture used to force the order.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the outcomes match the forced order.
@pytest.mark.parametrize("post_first", [True, False])
def test_post_vs_delete_in_both_orders(post_first: bool, monkeypatch, clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE), user_id)
    post_task = ("post", _post(transfer.id, user_id))
    delete_task = ("delete", _delete_transfer(transfer.id, user_id))

    results = _run_first_then_second(
        monkeypatch, account_transfer_repository, "get_account_transfer_by_id_for_update",
        post_task if post_first else delete_task,
        delete_task if post_first else post_task,
    )

    expected = (
        {"post": "posted", "delete": "deleted"} if post_first
        else {"post": "transfer_not_found", "delete": "deleted"}
    )
    assert results == expected
    assert _transfer_state(transfer.id) == (None, [])
    assert _balance(account_a, user_id) == Decimal("0.00")


# Tests P3 in both forced orders: posting locks Transfer -> Accounts while
# archiving locks the Account alone. If the post holds the Account locks
# first, it posts and the archive follows (posted + archived); if the
# archive commits first, the post sees the archived Account and is refused
# with the transfer still planned and no ledger rows.
# Parameters:
# - post_first: which operation is forced to hold the Account lock first.
# - monkeypatch: pytest fixture used to force the order.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the outcomes and final state match the order.
@pytest.mark.parametrize("post_first", [True, False])
def test_post_vs_archive_in_both_orders(post_first: bool, monkeypatch, clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE), user_id)
    post_task = ("post", _post(transfer.id, user_id))
    archive_task = ("archive", _update_account(
        account_b, user_id, AccountUpdate(status="archived"), "archived_ok",
    ))

    if post_first:
        results = _run_first_then_second(
            monkeypatch, account_repository, "get_accounts_by_ids_for_update",
            post_task, archive_task,
        )
        assert results == {"post": "posted", "archive": "archived_ok"}
        assert _transfer_state(transfer.id) == ("posted", ["credit", "debit"])
    else:
        results = _run_first_then_second(
            monkeypatch, account_repository, "get_account_by_id_for_update",
            archive_task, post_task,
        )
        assert results == {"post": "archived", "archive": "archived_ok"}
        assert _transfer_state(transfer.id) == ("planned", [])


# Tests P4: posting a planned A->B and a planned B->A transfer at the same
# time, repeatedly, never deadlocks (each locks its own transfer, then
# min(A, B) first), both post, each has exactly two rows, and the pair's
# combined balance is unchanged.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every round posts both transfers.
def test_opposite_planned_posts_do_not_deadlock(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", "1000.00"), ("B", "EUR", "500.00"))
    rounds = 5

    for _ in range(rounds):
        a_to_b = _create_committed(_request(account_a, account_b, PLANNED_DATE, "300.00"), user_id)
        b_to_a = _create_committed(_request(account_b, account_a, PLANNED_DATE, "100.00"), user_id)

        results = _run_concurrently({
            "a_to_b": _post(a_to_b.id, user_id),
            "b_to_a": _post(b_to_a.id, user_id),
        })

        assert results == {"a_to_b": "posted", "b_to_a": "posted"}
        assert _transfer_state(a_to_b.id) == ("posted", ["credit", "debit"])
        assert _transfer_state(b_to_a.id) == ("posted", ["credit", "debit"])

    assert _balance(account_a, user_id) == Decimal("1000.00") - rounds * Decimal("200.00")
    assert _balance(account_b, user_id) == Decimal("500.00") + rounds * Decimal("200.00")
    assert _balance(account_a, user_id) + _balance(account_b, user_id) == Decimal("1500.00")


# Tests P5: two planned transfers from the same source (A->B, A->C) posted
# concurrently both succeed - there is no available-balance rule - and the
# balances are the exact Decimal sums, with A negative.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both post and every balance is exact.
def test_parallel_posts_from_same_source(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b, account_c = _setup_accounts(
        user_id, ("A", "EUR", "100.00"), ("B", "EUR", None), ("C", "EUR", None),
    )
    to_b = _create_committed(_request(account_a, account_b, PLANNED_DATE, "80.00"), user_id)
    to_c = _create_committed(_request(account_a, account_c, PLANNED_DATE, "70.50"), user_id)

    results = _run_concurrently({
        "to_b": _post(to_b.id, user_id),
        "to_c": _post(to_c.id, user_id),
    })

    assert results == {"to_b": "posted", "to_c": "posted"}
    assert _balance(account_a, user_id) == Decimal("-50.50")
    assert _balance(account_b, user_id) == Decimal("80.00")
    assert _balance(account_c, user_id) == Decimal("70.50")
    assert _counts(user_id) == (2, 4)


# Tests P6: posting a planned transfer while one of its Accounts attempts
# an actual currency change. Whichever serializes first, the currency change
# is refused - by the planned-reference guard if it runs first, by the
# ledger-history rule if the post committed first - and the post succeeds.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the post succeeds and both Accounts keep EUR.
def test_post_vs_account_currency_change(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE), user_id)

    results = _run_concurrently({
        "post": _post(transfer.id, user_id),
        "currency": _update_account(account_a, user_id, AccountUpdate(currency="USD"), "changed"),
    })

    assert results["post"] == "posted", results
    assert results["currency"] in {"planned_reference", "history"}, results
    assert _transfer_state(transfer.id) == ("posted", ["credit", "debit"])
    assert (_currency(account_a), _currency(account_b)) == ("EUR", "EUR")


# Tests P7: posting a planned A->B transfer while an Income linked to A is
# moved to B. The Income move locks Income -> Accounts ascending, the post
# locks Transfer -> Accounts ascending; they share only the Account locks,
# taken in the same order, so neither deadlocks, both succeed, and every
# ledger row lands exactly once.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both succeed and the balances are exact.
def test_post_vs_income_move(clean_database: None) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE, "300.00"), user_id)
    setup_session = SessionLocal()
    try:
        income = income_service.create_income(
            db_session=setup_session,
            income_data=IncomeCreate(
                amount=Decimal("500.00"), currency="EUR", received_at=date(2026, 9, 5),
                source="salary", account_id=account_a,
            ),
            user_id=user_id,
        )
    finally:
        setup_session.close()

    def move_income(db_session: Session) -> str:
        income_service.update_income(
            db_session=db_session, income_id=income.id,
            income_data=IncomeUpdate(account_id=account_b), user_id=user_id,
        )
        return "moved"

    results = _run_concurrently({
        "post": _post(transfer.id, user_id),
        "income_move": move_income,
    })

    assert results == {"post": "posted", "income_move": "moved"}
    assert _transfer_state(transfer.id) == ("posted", ["credit", "debit"])
    assert _balance(account_a, user_id) == Decimal("-300.00")
    assert _balance(account_b, user_id) == Decimal("800.00")


# Tests P6 with a FORCED order: the post holds both Account locks first and
# commits, so the queued currency change sees ledger history and is refused
# by the history rule - the serialization the barrier-only test above does
# not reliably observe.
# Parameters:
# - monkeypatch: pytest fixture used to force the order.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the post wins and the change is refused by history.
def test_post_first_then_currency_change_is_refused_by_history(
    monkeypatch, clean_database: None,
) -> None:
    user_id = uuid4()
    account_a, account_b = _setup_accounts(user_id, ("A", "EUR", None), ("B", "EUR", None))
    transfer = _create_committed(_request(account_a, account_b, PLANNED_DATE), user_id)

    results = _run_first_then_second(
        monkeypatch, account_repository, "get_accounts_by_ids_for_update",
        ("post", _post(transfer.id, user_id)),
        ("currency", _update_account(account_a, user_id, AccountUpdate(currency="USD"), "changed")),
    )

    assert results == {"post": "posted", "currency": "history"}
    assert _transfer_state(transfer.id) == ("posted", ["credit", "debit"])
    assert (_currency(account_a), _currency(account_b)) == ("EUR", "EUR")
