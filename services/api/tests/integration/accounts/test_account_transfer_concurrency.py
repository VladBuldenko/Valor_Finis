import threading
from datetime import date
from decimal import Decimal
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_service,
    account_transaction_repository,
    account_transfer_service,
)
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
    AccountReferencedByPlannedTransferError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_errors import (
    AccountTransferCurrencyMismatchError,
    AccountTransferIdempotencyConflictError,
    AccountTransferNotFoundError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import AccountTransferCreate

# Real-thread concurrency tests for VF-018C (create/delete/Account
# lifecycle). Each thread uses its own Session/connection; a Barrier
# releases them at the same instant. Every outcome is mapped to a label, and
# any unexpected exception (including a PostgreSQL deadlock, which surfaces
# as OperationalError) becomes "error:<type>", which no test accepts.
# Manual posting concurrency belongs to VF-018D.

AS_OF = date(2026, 9, 28)
POSTED_DATE = date(2026, 9, 20)
PLANNED_DATE = date(2026, 10, 15)


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

    threads = [threading.Thread(target=runner, args=item) for item in tasks.items()]
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
