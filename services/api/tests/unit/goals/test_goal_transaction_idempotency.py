from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_service
from app.modules.goals.goal_errors import (
    GoalArchivedError,
    GoalInsufficientFundsError,
    GoalNotFoundError,
    GoalTransactionEffectiveDateInFutureError,
    GoalTransactionIdempotencyConflictError,
)
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate
from app.modules.goals.goal_transaction_models import GoalTransactionModel
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# VF-020B3 service-level tests for goal transaction runtime fields and
# create idempotency, against real PostgreSQL. "Today" is always pinned
# through as_of, so no assertion depends on the wall clock.

MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)
LAST_WEEK = date(2026, 9, 28)


def _create_goal(db_session, user_id, currency="EUR") -> GoalModel:
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(name="Vacation", target_amount=Decimal("2000"), currency=currency),
        user_id=user_id,
    )


def _request(
    type: str = "contribution",
    amount: str = "100.00",
    description: Optional[str] = None,
    effective_date: Optional[date] = None,
    key: Optional[UUID] = None,
) -> GoalTransactionCreate:
    return GoalTransactionCreate(
        type=type,
        amount=Decimal(amount),
        description=description,
        effective_date=effective_date,
        client_request_id=key,
    )


def _create(db_session, goal_id, user_id, request, as_of=MONDAY):
    return goal_service.create_or_replay_goal_transaction(
        db_session=db_session,
        goal_id=goal_id,
        transaction_data=request,
        user_id=user_id,
        as_of=as_of,
    )


def _row_count(db_session, user_id) -> int:
    db_session.rollback()
    return (
        db_session.query(GoalTransactionModel)
        .filter(GoalTransactionModel.user_id == user_id)
        .count()
    )


def _archive(db_session, goal_id, user_id) -> None:
    goal_service.update_goal(
        db_session=db_session,
        goal_id=goal_id,
        goal_data=GoalUpdate(status="archived"),
        user_id=user_id,
    )


# ------------------------------------------------------------------
# Runtime fields on new transactions
# ------------------------------------------------------------------


# Tests that a new transaction copies the goal's currency, gets the server
# date when effective_date is omitted, and has no key when none is sent.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the stored row matches.
def test_new_transaction_copies_goal_currency_and_defaults_effective_date(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="USD")

        result = _create(db_session, goal.id, user_id, _request())

        assert result.created is True
        assert result.transaction.currency == "USD"
        assert result.transaction.effective_date == MONDAY
        assert result.transaction.client_request_id is None
        stored = db_session.get(GoalTransactionModel, result.transaction.id)
        assert (stored.currency, stored.effective_date, stored.client_request_id) == (
            "USD", MONDAY, None,
        )
    finally:
        db_session.close()


# Tests that today and a past effective_date are accepted and stored as
# sent.
# Parameters:
# - requested: effective_date sent with the request.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the requested date is stored.
@pytest.mark.parametrize("requested", [MONDAY, LAST_WEEK])
def test_today_and_past_effective_dates_are_accepted(
    requested: date,
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        result = _create(db_session, goal.id, user_id, _request(effective_date=requested))

        assert result.created is True
        assert result.transaction.effective_date == requested
    finally:
        db_session.close()


# Tests that a new request with a future effective_date is rejected and
# nothing is written - without a key and with a key that is not used yet.
# Parameters:
# - key: request key (None, or a fresh unused key).
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the error is raised and no row exists.
@pytest.mark.parametrize("key", [None, uuid4()], ids=["no-key", "free-key"])
def test_future_effective_date_is_rejected(key: Optional[UUID], clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        with pytest.raises(GoalTransactionEffectiveDateInFutureError):
            _create(db_session, goal.id, user_id, _request(effective_date=TUESDAY, key=key))

        assert _row_count(db_session, user_id) == 0
    finally:
        db_session.close()


# Tests that for a new request the future-date rule is checked before the
# goal lookup, so it takes precedence over not-found - with or without a
# (free) key.
# Parameters:
# - key: request key (None, or a fresh unused key).
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the future-date error is raised.
@pytest.mark.parametrize("key", [None, uuid4()], ids=["no-key", "free-key"])
def test_future_effective_date_takes_precedence_over_missing_goal(
    key: Optional[UUID],
    clean_database: None,
) -> None:
    db_session = SessionLocal()

    try:
        with pytest.raises(GoalTransactionEffectiveDateInFutureError):
            _create(db_session, uuid4(), uuid4(), _request(effective_date=TUESDAY, key=key))
    finally:
        db_session.close()


# Tests that requests without a key keep the legacy behavior: each one
# creates a new transaction and no key is synthesized.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if two identical key-less requests create two rows.
def test_requests_without_key_always_create(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        first = _create(db_session, goal.id, user_id, _request())
        second = _create(db_session, goal.id, user_id, _request())

        assert first.created is True and second.created is True
        assert first.transaction.id != second.transaction.id
        assert second.transaction.client_request_id is None
        assert _row_count(db_session, user_id) == 2
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Idempotent replay
# ------------------------------------------------------------------


# Tests that the first request with a key creates the transaction and an
# exact replay returns the same transaction without writing a second row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay returns the original transaction.
def test_exact_replay_returns_original_transaction(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        request = _request(description="Payday", key=key)

        first = _create(db_session, goal.id, user_id, request)
        replay = _create(db_session, goal.id, user_id, request)

        assert first.created is True
        assert replay.created is False
        assert replay.transaction == first.transaction
        assert first.transaction.client_request_id == key
        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that the amount is compared as a Decimal value, never as text or
# float: "10", "10.0" and "10.00" all replay a transaction stored as 10.00,
# whichever form the original request used.
# Parameters:
# - original_amount: amount of the first request.
# - replay_amount: equivalent amount of the replay.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay is recognized.
@pytest.mark.parametrize(
    ("original_amount", "replay_amount"),
    [("10.00", "10"), ("10.00", "10.0"), ("10", "10.00"), ("10.0", "10")],
)
def test_replay_with_equivalent_decimal_amount_is_a_replay(
    original_amount: str,
    replay_amount: str,
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        first = _create(db_session, goal.id, user_id, _request(amount=original_amount, key=key))
        replay = _create(db_session, goal.id, user_id, _request(amount=replay_amount, key=key))

        assert replay.created is False
        assert replay.transaction.id == first.transaction.id
        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that a key reused with a materially different payload is a
# conflict, writes nothing and leaves the original row unchanged. The
# description is compared exactly as stored: the create path never
# normalizes it, so None and "" are different payloads.
# Parameters:
# - changed: field overrides of the conflicting request.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the conflict is raised and one row remains.
@pytest.mark.parametrize(
    "changed",
    [
        {"amount": "100.01"},
        {"type": "withdrawal"},
        {"description": "Different note"},
        {"description": ""},
        {"effective_date": LAST_WEEK},
    ],
    ids=["amount", "type", "description", "empty-vs-null-description", "explicit-date"],
)
def test_key_reused_with_different_payload_is_conflict(
    changed: dict,
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        # A funded goal, so a conflicting withdrawal would otherwise succeed.
        _create(db_session, goal.id, user_id, _request(amount="500.00"))
        original = _create(db_session, goal.id, user_id, _request(key=key))

        with pytest.raises(GoalTransactionIdempotencyConflictError):
            _create(db_session, goal.id, user_id, _request(key=key, **changed))

        assert _row_count(db_session, user_id) == 2
        stored = db_session.get(GoalTransactionModel, original.transaction.id)
        assert (stored.type, stored.amount, stored.description, stored.effective_date) == (
            "contribution", Decimal("100.00"), None, MONDAY,
        )
    finally:
        db_session.close()


# Tests that the key belongs to the user's whole goal transaction namespace:
# reusing it for another goal of the same user is a conflict, not a new
# transaction.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the conflict is raised and one row exists.
def test_key_reused_for_another_goal_is_conflict(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        first_goal = _create_goal(db_session, user_id)
        second_goal = _create_goal(db_session, user_id)
        _create(db_session, first_goal.id, user_id, _request(key=key))

        with pytest.raises(GoalTransactionIdempotencyConflictError):
            _create(db_session, second_goal.id, user_id, _request(key=key))

        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that a replay sent the next day that omits effective_date returns
# the original transaction with its original date - the server date is not
# recomputed for the comparison.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Tuesday replay returns the Monday row.
def test_omitted_date_replay_after_day_rollover_returns_original(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        first = _create(db_session, goal.id, user_id, _request(key=key), as_of=MONDAY)
        replay = _create(db_session, goal.id, user_id, _request(key=key), as_of=TUESDAY)

        assert replay.created is False
        assert replay.transaction.id == first.transaction.id
        assert replay.transaction.effective_date == MONDAY
        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that an explicit effective_date on a replay must equal the stored
# one: the original (server-assigned) date replays, the new day conflicts.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the matching explicit date replays.
def test_explicit_date_replay_must_match_stored_date(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        first = _create(db_session, goal.id, user_id, _request(key=key), as_of=MONDAY)

        replay = _create(
            db_session, goal.id, user_id, _request(key=key, effective_date=MONDAY), as_of=TUESDAY,
        )
        assert replay.created is False
        assert replay.transaction.id == first.transaction.id

        with pytest.raises(GoalTransactionIdempotencyConflictError):
            _create(
                db_session, goal.id, user_id,
                _request(key=key, effective_date=TUESDAY), as_of=TUESDAY,
            )

        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that a key already bound to a transaction answers for its original
# payload before any date validation: a replay stating a different date
# that is also in the future is an idempotency conflict (409), not a
# future-date rejection (422), and nothing is written (VF-020B3 M1).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the conflict is raised and one row remains.
def test_bound_key_with_future_different_date_is_conflict(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _create(db_session, goal.id, user_id, _request(key=key), as_of=MONDAY)

        with pytest.raises(GoalTransactionIdempotencyConflictError):
            _create(
                db_session, goal.id, user_id,
                _request(key=key, effective_date=date(2026, 10, 7)), as_of=TUESDAY,
            )

        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that the same key used by two users identifies two independent
# transactions.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both users create their own transaction.
def test_same_key_for_different_users_is_independent(clean_database: None) -> None:
    db_session = SessionLocal()
    first_user = uuid4()
    second_user = uuid4()
    key = uuid4()

    try:
        first_goal = _create_goal(db_session, first_user)
        second_goal = _create_goal(db_session, second_user)

        first = _create(db_session, first_goal.id, first_user, _request(key=key))
        second = _create(db_session, second_goal.id, second_user, _request(key=key))

        assert first.created is True and second.created is True
        assert first.transaction.id != second.transaction.id
        assert _row_count(db_session, first_user) == 1
        assert _row_count(db_session, second_user) == 1
    finally:
        db_session.close()


# Tests that a key can never reveal another user's transaction: replaying
# another user's exact request (their key, their goal) is resolved inside
# the caller's own namespace and ends as "goal not found".
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised and nothing is written.
def test_other_users_key_and_goal_never_return_their_transaction(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    owner = uuid4()
    intruder = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, owner)
        request = _request(key=key)
        _create(db_session, goal.id, owner, request)

        with pytest.raises(GoalNotFoundError):
            _create(db_session, goal.id, intruder, request)

        assert _row_count(db_session, intruder) == 0
        assert _row_count(db_session, owner) == 1
    finally:
        db_session.close()


# Tests the lock order of a keyed create: when the fast key lookup finds
# nothing, its transaction is ended before the goal row is locked, so the
# request holds no lock on goal_transactions while it waits for the goal -
# the same goals-then-goal_transactions order every write path and the
# VF-020B2 migration use.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to observe the goal lock call.
# Returns:
# - None. The test passes if no goal_transactions lock is held at that point.
def test_keyed_create_locks_goal_before_holding_goal_transactions_lock(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    held_locks: list = []
    original_lock = goal_repository.get_goal_by_id_for_update

    def observing_lock(**kwargs):
        held_locks.append(
            kwargs["db_session"].execute(
                text(
                    "SELECT count(*) FROM pg_locks l "
                    "JOIN pg_class c ON c.oid = l.relation "
                    "WHERE l.pid = pg_backend_pid() AND c.relname = 'goal_transactions'"
                )
            ).scalar_one()
        )
        return original_lock(**kwargs)

    try:
        goal = _create_goal(db_session, user_id)
        monkeypatch.setattr(goal_repository, "get_goal_by_id_for_update", observing_lock)

        result = _create(db_session, goal.id, user_id, _request(key=uuid4()))

        assert result.created is True
        assert held_locks == [0]
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Replay versus current goal lifecycle and balance
# ------------------------------------------------------------------


# Tests that an exact replay of a successful contribution still returns the
# original transaction after the goal was archived - a replay is not a new
# contribution - while a contribution with a fresh key is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay succeeds and the new key fails.
def test_contribution_replay_after_archive_returns_original(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        first = _create(db_session, goal.id, user_id, _request(key=key))
        _archive(db_session, goal.id, user_id)

        replay = _create(db_session, goal.id, user_id, _request(key=key))

        assert replay.created is False
        assert replay.transaction.id == first.transaction.id

        with pytest.raises(GoalArchivedError):
            _create(db_session, goal.id, user_id, _request(key=uuid4()))

        assert _row_count(db_session, user_id) == 1
    finally:
        db_session.close()


# Tests that a withdrawal with a fresh key still works on an archived goal
# (VF-020A P10) and records its key.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the withdrawal is created.
def test_archived_goal_allows_withdrawal_with_key(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _create(db_session, goal.id, user_id, _request(amount="100.00"))
        _archive(db_session, goal.id, user_id)

        result = _create(
            db_session, goal.id, user_id, _request(type="withdrawal", amount="40.00", key=key),
        )

        assert result.created is True
        assert result.transaction.client_request_id == key
    finally:
        db_session.close()


# Tests that an exact replay of a successful withdrawal returns the
# original transaction even though the current balance could no longer
# cover it - a replay is not a new withdrawal.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay succeeds while a new withdrawal fails.
def test_withdrawal_replay_after_balance_drop_returns_original(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _create(db_session, goal.id, user_id, _request(amount="100.00"))
        withdrawal_request = _request(type="withdrawal", amount="80.00", key=key)
        first = _create(db_session, goal.id, user_id, withdrawal_request)
        _create(db_session, goal.id, user_id, _request(type="withdrawal", amount="20.00"))

        replay = _create(db_session, goal.id, user_id, withdrawal_request)

        assert replay.created is False
        assert replay.transaction.id == first.transaction.id

        with pytest.raises(GoalInsufficientFundsError):
            _create(
                db_session, goal.id, user_id,
                _request(type="withdrawal", amount="80.00", key=uuid4()),
            )

        assert _row_count(db_session, user_id) == 3
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Legacy history
# ------------------------------------------------------------------


# Tests that history written before VF-020B3 - currency, effective_date and
# client_request_id all NULL - is still returned by the history read.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the legacy row is returned with None fields.
def test_history_returns_legacy_row_with_null_runtime_fields(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        legacy_id = uuid4()
        db_session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount) "
                "VALUES (:id, :goal_id, :user_id, 'opening_balance', 200)"
            ),
            {"id": str(legacy_id), "goal_id": str(goal.id), "user_id": str(user_id)},
        )
        db_session.commit()

        history = goal_service.get_goal_transactions(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        )

        assert [t.id for t in history] == [legacy_id]
        assert (history[0].currency, history[0].effective_date, history[0].client_request_id) == (
            None, None, None,
        )
    finally:
        db_session.close()
