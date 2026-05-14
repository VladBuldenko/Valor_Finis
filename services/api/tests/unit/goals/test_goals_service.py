from datetime import date
from decimal import Decimal

from app.modules.goals import goal_repository, goal_service
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Resets the in-memory goal repository state before each test.
# This helper exists to keep service tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    goal_repository.goals_storage.clear()
    goal_repository.next_goal_id = 1


# Tests that the service creates a new financial goal.
# This test exists to verify that the service layer correctly delegates goal creation to the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created goal contains expected data.
def test_service_create_goal_creates_goal() -> None:
    # Arrange
    reset_repository_state()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    # Act
    created_goal = goal_service.create_goal(goal_data)

    # Assert
    assert isinstance(created_goal, GoalResponse)
    assert created_goal.id == 1
    assert created_goal.name == "Vacation"
    assert created_goal.target_amount == Decimal("2000")


# Tests that the service returns all financial goals.
# This test exists to verify that the service layer can retrieve goals through the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if returned goals include previously created goals.
def test_service_get_goals_returns_goals() -> None:
    # Arrange
    reset_repository_state()

    goal_data = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        current_amount=Decimal("500"),
        deadline=date(2026, 12, 31),
    )

    created_goal = goal_service.create_goal(goal_data)

    # Act
    goals = goal_service.get_goals()

    # Assert
    assert len(goals) == 1
    assert goals[0] == created_goal