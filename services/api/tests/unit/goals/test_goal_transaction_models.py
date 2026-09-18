from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_models import GoalTransactionModel


def _create_goal(db_session, user_id, current_amount=Decimal("0")) -> GoalModel:
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(
            name="Emergency fund",
            target_amount=Decimal("1000"),
            current_amount=current_amount,
            currency="EUR",
            target_date=date(2026, 12, 31),
            status="active",
        ),
        user_id=user_id,
    )


# Tests that a transaction with a positive amount and a valid type persists.
# This test exists to prove the baseline happy path for the new ledger table
# before exercising its constraints.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted with the expected fields.
def test_goal_transaction_with_positive_amount_and_valid_type_persists(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        transaction = GoalTransactionModel(
            goal_id=goal.id,
            user_id=user_id,
            type="contribution",
            amount=Decimal("150.00"),
            description="Payday transfer",
        )
        db_session.add(transaction)
        db_session.commit()
        db_session.refresh(transaction)

        assert transaction.id is not None
        assert transaction.goal_id == goal.id
        assert transaction.user_id == user_id
        assert transaction.type == "contribution"
        assert transaction.amount == Decimal("150.00")
        assert transaction.description == "Payday transfer"
        assert transaction.created_at is not None
    finally:
        db_session.close()


# Tests that a zero amount is rejected by the amount > 0 CHECK constraint.
# This test exists to prove the constraint is enforced at the database level,
# not only in application code that does not exist yet in this slice.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_zero_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        db_session.add(
            GoalTransactionModel(
                goal_id=goal.id,
                user_id=user_id,
                type="contribution",
                amount=Decimal("0.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for zero amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a negative amount is rejected by the amount > 0 CHECK constraint.
# This test exists to prove direction must be carried by type, never by sign.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_negative_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        db_session.add(
            GoalTransactionModel(
                goal_id=goal.id,
                user_id=user_id,
                type="withdrawal",
                amount=Decimal("-50.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for negative amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that every allowed type value is accepted by the type CHECK constraint.
# This test exists to prove opening_balance/contribution/withdrawal are all
# valid, matching the approved VF-016 type set.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all three rows persist successfully.
def test_goal_transaction_all_allowed_types_accepted(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        for allowed_type in ("opening_balance", "contribution", "withdrawal"):
            db_session.add(
                GoalTransactionModel(
                    goal_id=goal.id,
                    user_id=user_id,
                    type=allowed_type,
                    amount=Decimal("10.00"),
                )
            )
        db_session.commit()

        rows = (
            db_session.query(GoalTransactionModel)
            .filter(GoalTransactionModel.goal_id == goal.id)
            .all()
        )
        assert {row.type for row in rows} == {
            "opening_balance",
            "contribution",
            "withdrawal",
        }
    finally:
        db_session.close()


# Tests that a type outside the allowed set is rejected by the type CHECK
# constraint.
# This test exists to prove type validity is enforced at the database level,
# not only in application/Pydantic code that does not exist yet in this slice.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_invalid_type_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        db_session.add(
            GoalTransactionModel(
                goal_id=goal.id,
                user_id=user_id,
                type="refund",
                amount=Decimal("10.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid type"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a transaction referencing a non-existent goal is rejected by the
# foreign key constraint.
# This test exists to prove goal_id is FK-enforced, not merely a plain UUID
# column.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_foreign_key_to_goal_enforced(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            GoalTransactionModel(
                goal_id=uuid4(),
                user_id=user_id,
                type="contribution",
                amount=Decimal("10.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for missing goal"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that user_id is required (NOT NULL) at the database level.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_user_id_required(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        db_session.add(
            GoalTransactionModel(
                goal_id=goal.id,
                user_id=None,
                type="contribution",
                amount=Decimal("10.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for missing user_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that goal_id is required (NOT NULL) at the database level.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_goal_transaction_goal_id_required(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            GoalTransactionModel(
                goal_id=None,
                user_id=user_id,
                type="contribution",
                amount=Decimal("10.00"),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for missing goal_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a Goal with existing GoalTransaction history cannot be deleted
# directly at the database level.
# This test exists to prove the RESTRICT foreign key (not CASCADE) keeps
# financial history from silently disappearing when a Goal row is deleted,
# per the approved VF-016 architecture.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if deleting the goal raises IntegrityError and the
#   transaction row still exists afterward.
def test_goal_with_transaction_history_cannot_be_deleted(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, current_amount=Decimal("100"))

        transaction = GoalTransactionModel(
            goal_id=goal.id,
            user_id=user_id,
            type="opening_balance",
            amount=Decimal("100.00"),
        )
        db_session.add(transaction)
        db_session.commit()

        try:
            db_session.query(GoalModel).filter(GoalModel.id == goal.id).delete()
            db_session.commit()
            assert False, "expected IntegrityError deleting a funded goal"
        except IntegrityError:
            db_session.rollback()

        surviving = (
            db_session.query(GoalTransactionModel)
            .filter(GoalTransactionModel.goal_id == goal.id)
            .all()
        )
        assert len(surviving) == 1
    finally:
        db_session.close()


# Tests that transactions for different users each retain their own correct
# user_id and are not cross-attributed.
# This test exists as the foundation-level check for the ownership model
# that VF-016C's API will rely on (denormalized user_id, never inferred
# solely through the goal_id join).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each transaction's user_id matches its own
#   owner, not the other user's.
def test_goal_transactions_retain_correct_user_id_per_owner(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        other_goal = _create_goal(db_session, other_user_id)

        db_session.add(
            GoalTransactionModel(
                goal_id=goal.id,
                user_id=user_id,
                type="contribution",
                amount=Decimal("20.00"),
            )
        )
        db_session.add(
            GoalTransactionModel(
                goal_id=other_goal.id,
                user_id=other_user_id,
                type="contribution",
                amount=Decimal("30.00"),
            )
        )
        db_session.commit()

        user_transactions = (
            db_session.query(GoalTransactionModel)
            .filter(GoalTransactionModel.user_id == user_id)
            .all()
        )
        other_user_transactions = (
            db_session.query(GoalTransactionModel)
            .filter(GoalTransactionModel.user_id == other_user_id)
            .all()
        )

        assert len(user_transactions) == 1
        assert user_transactions[0].goal_id == goal.id
        assert len(other_user_transactions) == 1
        assert other_user_transactions[0].goal_id == other_goal.id
    finally:
        db_session.close()
