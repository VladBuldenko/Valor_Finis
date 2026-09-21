from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository
from app.modules.goals.goal_errors import GoalNotFoundError
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate


# Tests that the repository creates a new financial goal in the database.
# This test exists to verify that goal data and authenticated user id
# are converted into GoalModel and persisted through SQLAlchemy.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created database model contains the expected values.
def test_create_goal_creates_new_goal(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        currency="EUR",
        target_date=date(2026, 12, 31),
        status="active",
    )

    try:
        # Act
        created_goal = goal_repository.create_goal(
            db_session=db_session,
            goal_data=goal_data,
            user_id=user_id,
        )

        # Assert
        assert isinstance(created_goal, GoalModel)
        assert created_goal.user_id == user_id
        assert created_goal.name == goal_data.name
        assert created_goal.target_amount == Decimal("2000")
        assert created_goal.current_amount == Decimal("0")
        assert created_goal.currency == goal_data.currency
        assert created_goal.target_date == goal_data.target_date
        assert created_goal.status == goal_data.status
        assert created_goal.id is not None
        assert created_goal.created_at is not None
        assert created_goal.updated_at is not None
    finally:
        db_session.close()


# Tests that the repository returns goal records for a specific user.
# This test exists to verify that users only receive their own goals from the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's goal is returned.
def test_get_goals_returns_goals_for_user(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        currency="EUR",
        target_date=date(2026, 12, 31),
        status="active",
    )

    other_user_goal_data = GoalCreate(
        name="Laptop",
        target_amount=Decimal("1500"),
        currency="EUR",
        target_date=date(2026, 10, 31),
        status="active",
    )

    try:
        goal_repository.create_goal(
            db_session=db_session,
            goal_data=user_goal_data,
            user_id=user_id,
        )
        goal_repository.create_goal(
            db_session=db_session,
            goal_data=other_user_goal_data,
            user_id=other_user_id,
        )

        # Act
        goals = goal_repository.get_goals(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(goals) == 1
        assert isinstance(goals[0], GoalModel)
        assert goals[0].user_id == user_id
        assert goals[0].name == user_goal_data.name
        assert goals[0].target_amount == Decimal("2000")
        assert goals[0].current_amount == Decimal("0")
        assert goals[0].currency == user_goal_data.currency
        assert goals[0].target_date == user_goal_data.target_date
        assert goals[0].status == user_goal_data.status
    finally:
        db_session.close()


# Tests that get_goal_by_id_for_update returns the owned goal, locked.
# This test exists to verify the row-locking read path used by every
# balance-changing goal transaction write (VF-016C) returns the correct
# goal for its owner.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the correct GoalModel instance is returned.
def test_get_goal_by_id_for_update_returns_owned_goal(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created_goal = goal_repository.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(
                name="Vacation",
                target_amount=Decimal("2000"),
                currency="EUR",
            ),
            user_id=user_id,
        )

        # Act
        locked_goal = goal_repository.get_goal_by_id_for_update(
            db_session=db_session,
            goal_id=created_goal.id,
            user_id=user_id,
        )

        # Assert
        assert locked_goal.id == created_goal.id
        assert locked_goal.user_id == user_id
    finally:
        db_session.close()


# Tests that get_goal_by_id_for_update raises GoalNotFoundError for a
# missing or other-user goal.
# This test exists to verify ownership is enforced identically to the
# non-locking read path.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if GoalNotFoundError is raised.
def test_get_goal_by_id_for_update_raises_not_found_for_other_user(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        created_goal = goal_repository.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(
                name="Vacation",
                target_amount=Decimal("2000"),
                currency="EUR",
            ),
            user_id=other_user_id,
        )

        # Act / Assert
        with pytest.raises(GoalNotFoundError):
            goal_repository.get_goal_by_id_for_update(
                db_session=db_session,
                goal_id=created_goal.id,
                user_id=user_id,
            )
    finally:
        db_session.close()