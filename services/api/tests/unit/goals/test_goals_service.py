from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.goals import goal_service
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Tests that the service creates a new financial goal.
# This test exists to verify that the service maps the created database model to GoalResponse.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a GoalResponse object is returned with expected values.
def test_service_create_goal_creates_goal_response(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    goal_data = GoalCreate(
        user_id=user_id,
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        currency="EUR",
        target_date=date(2026, 12, 31),
        status="active",
    )

    try:
        # Act
        created_goal = goal_service.create_goal(
            db_session=db_session,
            goal_data=goal_data,
        )

        # Assert
        assert isinstance(created_goal, GoalResponse)
        assert created_goal.user_id == user_id
        assert created_goal.name == goal_data.name
        assert created_goal.target_amount == Decimal("2000")
        assert created_goal.current_amount == Decimal("500")
        assert created_goal.currency == goal_data.currency
        assert created_goal.target_date == goal_data.target_date
        assert created_goal.status == goal_data.status
    finally:
        db_session.close()


# Tests that the service returns goals for a specific user.
# This test exists to verify that the service retrieves user-scoped goals and returns response schemas.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's goals are returned.
def test_service_get_goals_returns_user_goal_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_goal_data = GoalCreate(
        user_id=user_id,
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        currency="EUR",
        target_date=date(2026, 12, 31),
        status="active",
    )

    other_user_goal_data = GoalCreate(
        user_id=other_user_id,
        name="Laptop",
        target_amount=Decimal("1500"),
        current_amount=Decimal("300"),
        currency="EUR",
        target_date=date(2026, 10, 31),
        status="active",
    )

    try:
        goal_service.create_goal(
            db_session=db_session,
            goal_data=user_goal_data,
        )
        goal_service.create_goal(
            db_session=db_session,
            goal_data=other_user_goal_data,
        )

        # Act
        goals = goal_service.get_goals(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(goals) == 1
        assert isinstance(goals[0], GoalResponse)
        assert goals[0].user_id == user_id
        assert goals[0].name == user_goal_data.name
        assert goals[0].target_amount == Decimal("2000")
        assert goals[0].current_amount == Decimal("500")
        assert goals[0].currency == user_goal_data.currency
        assert goals[0].target_date == user_goal_data.target_date
        assert goals[0].status == user_goal_data.status
    finally:
        db_session.close()