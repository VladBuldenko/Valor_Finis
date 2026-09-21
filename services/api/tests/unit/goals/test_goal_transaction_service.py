from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalInsufficientFundsError, GoalNotFoundError
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_schemas import (
    GoalTransactionCreate,
    GoalTransactionResponse,
)


def _create_goal(db_session, user_id, target_amount=Decimal("2000")):
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(
            name="Vacation",
            target_amount=target_amount,
            currency="EUR",
        ),
        user_id=user_id,
    )


# Tests that a contribution on a freshly created (zero-balance) goal
# succeeds and the ledger-derived balance is copied to the transitional
# current_amount column.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the transaction and synced balance are correct.
def test_create_goal_transaction_contribution_on_zero_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        result = goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("150.00"),
            ),
            user_id=user_id,
        )

        assert isinstance(result, GoalTransactionResponse)
        assert result.type == "contribution"
        assert result.amount == Decimal("150.00")
        assert result.goal_id == goal.id
        assert result.user_id == user_id

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("150.00")
    finally:
        db_session.close()


# Tests that repeated contributions accumulate correctly.
# This test exists to verify the ledger balance is recalculated from all
# transaction history on every write, not incrementally trusted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the final balance is the sum of all contributions.
def test_create_goal_transaction_repeated_contributions_accumulate(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        for amount in (Decimal("100.00"), Decimal("50.00"), Decimal("25.00")):
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal.id,
                transaction_data=GoalTransactionCreate(
                    type="contribution",
                    amount=amount,
                ),
                user_id=user_id,
            )

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("175.00")
    finally:
        db_session.close()


# Tests that a withdrawal reduces the balance correctly.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the balance is reduced by the withdrawal amount.
def test_create_goal_transaction_withdrawal_reduces_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("200.00"),
            ),
            user_id=user_id,
        )

        result = goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="withdrawal",
                amount=Decimal("80.00"),
            ),
            user_id=user_id,
        )

        assert result.type == "withdrawal"

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("120.00")
    finally:
        db_session.close()


# Tests that a withdrawal exactly equal to the current balance succeeds and
# leaves the balance at exactly zero.
# This test exists to verify the boundary condition (amount == balance)
# does not incorrectly trigger the insufficient-funds rejection.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the withdrawal succeeds and balance is 0.
def test_create_goal_transaction_withdrawal_equal_to_balance_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("100.00"),
            ),
            user_id=user_id,
        )

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="withdrawal",
                amount=Decimal("100.00"),
            ),
            user_id=user_id,
        )

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("0.00")
    finally:
        db_session.close()


# Tests that a withdrawal greater than the current balance is rejected with
# GoalInsufficientFundsError.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalInsufficientFundsError is raised.
def test_create_goal_transaction_withdrawal_greater_than_balance_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("50.00"),
            ),
            user_id=user_id,
        )

        with pytest.raises(GoalInsufficientFundsError):
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal.id,
                transaction_data=GoalTransactionCreate(
                    type="withdrawal",
                    amount=Decimal("50.01"),
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a failed withdrawal creates no transaction and does not
# change current_amount.
# This test exists to verify atomicity: the ledger insert and the
# transitional balance update must never partially apply.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if no new transaction row exists and the balance
#   is unchanged.
def test_create_goal_transaction_failed_withdrawal_changes_nothing(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("50.00"),
            ),
            user_id=user_id,
        )

        transactions_before = goal_transaction_repository.get_transactions_for_goal(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
        )

        with pytest.raises(GoalInsufficientFundsError):
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal.id,
                transaction_data=GoalTransactionCreate(
                    type="withdrawal",
                    amount=Decimal("999.00"),
                ),
                user_id=user_id,
            )

        transactions_after = goal_transaction_repository.get_transactions_for_goal(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
        )

        assert len(transactions_after) == len(transactions_before) == 1

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("50.00")
    finally:
        db_session.close()


# Tests that a contribution pushing the balance above target_amount is
# allowed (overfunding).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the overfunding contribution succeeds.
def test_create_goal_transaction_overfunding_is_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, target_amount=Decimal("100"))

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("150.00"),
            ),
            user_id=user_id,
        )

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("150.00")
        assert goal.current_amount > goal.target_amount
    finally:
        db_session.close()


# Tests that an existing opening_balance transaction participates in the
# ledger balance calculation used by a subsequent contribution/withdrawal.
# This test exists to verify the migration-created legacy balance is never
# ignored by the new write path.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the opening_balance amount is included.
def test_create_goal_transaction_includes_existing_opening_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="opening_balance",
            amount=Decimal("200.00"),
            description=None,
        )

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("50.00"),
            ),
            user_id=user_id,
        )

        db_session.refresh(goal)
        assert goal.current_amount == Decimal("250.00")
    finally:
        db_session.close()


# Tests that transaction history includes migration-created opening_balance
# entries alongside contributions/withdrawals.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all three transaction types are present.
def test_get_goal_transactions_includes_opening_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="opening_balance",
            amount=Decimal("200.00"),
            description=None,
        )
        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("50.00"),
            ),
            user_id=user_id,
        )

        history = goal_service.get_goal_transactions(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
        )

        types = {transaction.type for transaction in history}
        assert types == {"opening_balance", "contribution"}
        assert len(history) == 2
    finally:
        db_session.close()


# Tests that transaction history is correctly isolated per owner.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each user only sees their own goal's history.
def test_get_goal_transactions_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        other_goal = _create_goal(db_session, other_user_id)

        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("10.00"),
            ),
            user_id=user_id,
        )
        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=other_goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("20.00"),
            ),
            user_id=other_user_id,
        )

        history = goal_service.get_goal_transactions(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
        )

        assert len(history) == 1
        assert history[0].amount == Decimal("10.00")
    finally:
        db_session.close()


# Tests that creating a transaction for a missing/other-user goal behaves
# as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised.
def test_create_goal_transaction_missing_goal_raises_not_found(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_goal = _create_goal(db_session, other_user_id)

        with pytest.raises(GoalNotFoundError):
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=other_goal.id,
                transaction_data=GoalTransactionCreate(
                    type="contribution",
                    amount=Decimal("10.00"),
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that reading transaction history for a missing/other-user goal
# behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised.
def test_get_goal_transactions_missing_goal_raises_not_found(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_goal = _create_goal(db_session, other_user_id)

        with pytest.raises(GoalNotFoundError):
            goal_service.get_goal_transactions(
                db_session=db_session,
                goal_id=other_goal.id,
                user_id=user_id,
            )
    finally:
        db_session.close()
