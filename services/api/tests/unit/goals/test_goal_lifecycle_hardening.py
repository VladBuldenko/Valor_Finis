from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_service, goal_transaction_repository
from app.modules.goals.goal_errors import (
    GoalCurrencyImmutableError,
    GoalDeletionNotAllowedError,
    GoalNotFoundError,
)
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate


def _create_goal(db_session, user_id, currency="EUR", target_amount=Decimal("2000")) -> GoalModel:
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(name="Vacation", target_amount=target_amount, currency=currency),
        user_id=user_id,
    )


def _add_transaction(db_session, goal_id, user_id, type, amount) -> None:
    goal_transaction_repository.create_transaction(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
        type=type,
        amount=amount,
        description=None,
    )


# ------------------------------------------------------------------
# Repository: has_transactions_for_goal
# ------------------------------------------------------------------


# Tests that a goal with no transactions reports no history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_goal returns False.
def test_has_transactions_for_goal_false_when_no_transactions(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        assert goal_transaction_repository.has_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        ) is False
    finally:
        db_session.close()


# Tests that a goal whose only transaction is opening_balance is reported
# as having history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_goal returns True.
def test_has_transactions_for_goal_true_for_opening_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("100.00"))

        assert goal_transaction_repository.has_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        ) is True
    finally:
        db_session.close()


# Tests that a goal with a contribution followed by an equal withdrawal
# (ledger balance 0) is still reported as having history.
# This test exists to prove balance is never used as a proxy for history
# (VF-016E) - a zero-balance goal can still have real financial history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_goal returns True even
#   though the ledger balance is exactly 0.
def test_has_transactions_for_goal_true_for_zero_balance_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("100.00"))
        _add_transaction(db_session, goal.id, user_id, "withdrawal", Decimal("100.00"))

        balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")

        assert goal_transaction_repository.has_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        ) is True
    finally:
        db_session.close()


# Tests that another user's transactions never count as this goal's
# history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if has_transactions_for_goal returns False.
def test_has_transactions_for_goal_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        # A transaction belonging to a completely different goal/user must
        # never leak into this goal's history check.
        other_goal = _create_goal(db_session, other_user_id)
        _add_transaction(db_session, other_goal.id, other_user_id, "contribution", Decimal("10.00"))

        assert goal_transaction_repository.has_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        ) is False
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Service: currency immutability
# ------------------------------------------------------------------


# Tests that a goal with no transaction history can change currency.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the PATCH succeeds with the new currency.
def test_update_goal_currency_change_allowed_without_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(currency="USD"),
            user_id=user_id,
        )

        assert response.currency == "USD"
    finally:
        db_session.close()


# Tests that currency normalization (lowercase -> uppercase) still works
# for a currency change with no history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the stored/returned currency is uppercase.
def test_update_goal_currency_normalizes_without_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(currency="usd"),
            user_id=user_id,
        )

        assert response.currency == "USD"
    finally:
        db_session.close()


# Tests that a goal with contribution history cannot change currency.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalCurrencyImmutableError is raised.
def test_update_goal_currency_change_rejected_with_contribution_history(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        with pytest.raises(GoalCurrencyImmutableError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal.id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a goal whose only history is a migration-created
# opening_balance cannot change currency.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalCurrencyImmutableError is raised.
def test_update_goal_currency_change_rejected_with_opening_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("300.00"))

        with pytest.raises(GoalCurrencyImmutableError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal.id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a zero-balance goal (contribution fully withdrawn) still
# cannot change currency.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalCurrencyImmutableError is raised even
#   though the ledger balance is 0.
def test_update_goal_currency_change_rejected_with_zero_balance_history(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("40.00"))
        _add_transaction(db_session, goal.id, user_id, "withdrawal", Decimal("40.00"))

        with pytest.raises(GoalCurrencyImmutableError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal.id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that resending the same normalized currency after history exists
# is allowed (not an actual change).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the PATCH succeeds despite existing history.
def test_update_goal_same_normalized_currency_allowed_with_history(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            # Lowercase input, same currency after normalization - must
            # not be treated as an actual change.
            goal_data=GoalUpdate(currency="eur"),
            user_id=user_id,
        )

        assert response.currency == "EUR"
    finally:
        db_session.close()


# Tests that a non-currency field can still be updated after history
# exists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the name change succeeds.
def test_update_goal_non_currency_field_succeeds_with_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(name="Renamed vacation"),
            user_id=user_id,
        )

        assert response.name == "Renamed vacation"
        assert response.currency == "EUR"
    finally:
        db_session.close()


# Tests that lowering target_amount below the ledger balance still
# succeeds after history exists (unaffected by currency-immutability
# logic).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the PATCH succeeds and the goal is overfunded.
def test_update_goal_lowering_target_below_balance_still_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR", target_amount=Decimal("2000"))
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("1200.00"))

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(target_amount=Decimal("1000")),
            user_id=user_id,
        )

        assert response.target_amount == Decimal("1000.00")
        assert response.current_amount == Decimal("1200.00")
    finally:
        db_session.close()


# Tests that updating another user's goal behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised.
def test_update_goal_other_user_goal_raises_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_goal = _create_goal(db_session, other_user_id, currency="EUR")

        with pytest.raises(GoalNotFoundError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=other_goal.id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a rejected currency change does not mutate the goal at all,
# and leaves the transaction history untouched.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the goal's stored currency/name and its
#   transaction count are unchanged after the rejected PATCH.
def test_update_goal_rejected_currency_change_does_not_mutate_state(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        transactions_before = goal_transaction_repository.get_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        )

        with pytest.raises(GoalCurrencyImmutableError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal.id,
                goal_data=GoalUpdate(currency="USD", name="Attempted rename"),
                user_id=user_id,
            )

        verify_session = SessionLocal()
        try:
            raw_goal = (
                verify_session.query(GoalModel).filter(GoalModel.id == goal.id).first()
            )
            assert raw_goal.currency == "EUR"
            assert raw_goal.name == "Vacation"
        finally:
            verify_session.close()

        transactions_after = goal_transaction_repository.get_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        )
        assert len(transactions_after) == len(transactions_before) == 1
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Service: safe delete
# ------------------------------------------------------------------


# Tests that a goal with no transaction history can be hard-deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the goal no longer exists afterward.
def test_delete_goal_succeeds_without_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)

        remaining = goal_repository.get_goals(db_session=db_session, user_id=user_id)
        assert remaining == []
    finally:
        db_session.close()


# Tests that a goal with contribution history cannot be deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalDeletionNotAllowedError is raised.
def test_delete_goal_rejected_with_contribution_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        with pytest.raises(GoalDeletionNotAllowedError):
            goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)
    finally:
        db_session.close()


# Tests that a goal whose only history is opening_balance cannot be
# deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalDeletionNotAllowedError is raised.
def test_delete_goal_rejected_with_opening_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("100.00"))

        with pytest.raises(GoalDeletionNotAllowedError):
            goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)
    finally:
        db_session.close()


# Tests that a zero-balance goal (contribution fully withdrawn) still
# cannot be deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalDeletionNotAllowedError is raised even
#   though the ledger balance is 0.
def test_delete_goal_rejected_with_zero_balance_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("70.00"))
        _add_transaction(db_session, goal.id, user_id, "withdrawal", Decimal("70.00"))

        with pytest.raises(GoalDeletionNotAllowedError):
            goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)
    finally:
        db_session.close()


# Tests that deleting another user's goal behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised.
def test_delete_goal_other_user_goal_raises_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_goal = _create_goal(db_session, other_user_id)

        with pytest.raises(GoalNotFoundError):
            goal_service.delete_goal(
                db_session=db_session, goal_id=other_goal.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a rejected delete leaves both the goal and its transaction
# history fully intact.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the goal and its transactions are unchanged.
def test_delete_goal_rejected_leaves_goal_and_history_intact(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        with pytest.raises(GoalDeletionNotAllowedError):
            goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)

        remaining_goals = goal_repository.get_goals(db_session=db_session, user_id=user_id)
        assert len(remaining_goals) == 1
        assert remaining_goals[0].id == goal.id

        transactions = goal_transaction_repository.get_transactions_for_goal(
            db_session=db_session, goal_id=goal.id, user_id=user_id,
        )
        assert len(transactions) == 1
    finally:
        db_session.close()


# Tests that archiving (PATCH status="archived") still works for a goal
# that has transaction history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the archive PATCH succeeds.
def test_archive_goal_succeeds_with_transaction_history(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(status="archived"),
            user_id=user_id,
        )

        assert response.status == "archived"
        assert response.current_amount == Decimal("50.00")
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Opening-balance-only goal: full lifecycle coverage
# ------------------------------------------------------------------


# Tests the full VF-016E hardening behavior for a goal whose only history
# is a migration-created opening_balance row: currency cannot change, the
# goal cannot be deleted, but it can still be archived and other metadata
# can still be edited.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all four behaviors hold.
def test_opening_balance_only_goal_full_lifecycle_hardening(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, currency="EUR")
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("500.00"))

        # Currency cannot change.
        with pytest.raises(GoalCurrencyImmutableError):
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal.id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )

        # Cannot be deleted.
        with pytest.raises(GoalDeletionNotAllowedError):
            goal_service.delete_goal(db_session=db_session, goal_id=goal.id, user_id=user_id)

        # Can still be archived.
        archived = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(status="archived"),
            user_id=user_id,
        )
        assert archived.status == "archived"

        # Other metadata can still be edited.
        renamed = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(name="Renamed"),
            user_id=user_id,
        )
        assert renamed.name == "Renamed"
        assert renamed.current_amount == Decimal("500.00")
    finally:
        db_session.close()
