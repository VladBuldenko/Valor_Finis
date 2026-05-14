from datetime import datetime

from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


goals_storage: list[GoalResponse] = []
next_goal_id = 1


# Creates a new financial goal in temporary in-memory storage.
# This function exists to isolate goal storage logic from business logic.
# Parameters:
# - goal_data: validated goal input data.
# Returns:
# - GoalResponse object with generated id and created_at timestamp.
def create_goal(goal_data: GoalCreate) -> GoalResponse:
    global next_goal_id

    goal = GoalResponse(
        id=next_goal_id,
        name=goal_data.name,
        target_amount=goal_data.target_amount,
        current_amount=goal_data.current_amount,
        deadline=goal_data.deadline,
        created_at=datetime.utcnow(),
    )

    goals_storage.append(goal)
    next_goal_id += 1

    return goal


# Returns all financial goals from temporary in-memory storage.
# This function exists to keep goal retrieval logic inside the repository layer.
# Parameters:
# - None.
# Returns:
# - List of GoalResponse objects.
def get_goals() -> list[GoalResponse]:
    return goals_storage