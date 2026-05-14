from datetime import date, datetime
from decimal import Decimal

from app.modules.goals import goal_repository
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Resets the in-memory goal repository state before each test.
# This helper exists to keep repository tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    goal_repository.goals_storage.clear()
    goal_repository.next_goal_id = 1


# Tests that the repository creates a new financial goal successfully.
# This test exists to verify that goal data can be stored in memory.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created goal contains expected data.
def test_create_goal_creates_new_goal() -> None:
    # Arrange
    reset_repository_state()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    # Act
    created_goal = goal_repository.create_goal(goal_data)

    # Assert
    assert isinstance(created_goal, GoalResponse)
    assert created_goal.name == "Vacation"
    assert created_goal.target_amount == Decimal("2000")
    assert created_goal.current_amount == Decimal("500")
    assert created_goal.deadline == date(2026, 12, 31)


# Tests that the repository generates an auto-incremented goal ID.
# This test exists to verify that each created goal receives a unique identifier.
# Parameters:
# - None.
# Returns:
# - None. The test passes if goal IDs are generated in sequence.
def test_create_goal_generates_incremental_id() -> None:
    # Arrange
    reset_repository_state()

    first_goal = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    second_goal = GoalCreate(
        name="Laptop",
        target_amount=Decimal("1500"),
        current_amount=Decimal("300"),
        deadline=date(2026, 10, 31),
    )

    # Act
    created_first_goal = goal_repository.create_goal(first_goal)
    created_second_goal = goal_repository.create_goal(second_goal)

    # Assert
    assert created_first_goal.id == 1
    assert created_second_goal.id == 2


# Tests that the repository adds creation timestamp to a new goal.
# This test exists to verify that created_at is generated automatically.
# Parameters:
# - None.
# Returns:
# - None. The test passes if created_at is a datetime value.
def test_create_goal_generates_created_at_timestamp() -> None:
    # Arrange
    reset_repository_state()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    # Act
    created_goal = goal_repository.create_goal(goal_data)

    # Assert
    assert isinstance(created_goal.created_at, datetime)


# Tests that the repository returns all saved financial goals.
# This test exists to verify that stored goals can be retrieved.
# Parameters:
# - None.
# Returns:
# - None. The test passes if get_goals returns previously created goals.
def test_get_goals_returns_saved_goals() -> None:
    # Arrange
    reset_repository_state()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    created_goal = goal_repository.create_goal(goal_data)

    # Act
    goals = goal_repository.get_goals()

    # Assert
    assert len(goals) == 1
    assert goals[0] == created_goal