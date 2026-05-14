from app.modules.goals import goal_repository
from app.modules.goals.goal_schemas import GoalCreate, GoalResponse


# Creates a new financial goal using validated goal data.
# This function exists to keep goal business logic separate from API and storage layers.
# Parameters:
# - goal_data: validated goal input data.
# Returns:
# - GoalResponse object created by the repository.
def create_goal(goal_data: GoalCreate) -> GoalResponse:
    return goal_repository.create_goal(goal_data)


# Returns all created financial goals.
# This function exists to provide a clean service layer between router and repository.
# Parameters:
# - None.
# Returns:
# - List of GoalResponse objects.
def get_goals() -> list[GoalResponse]:
    return goal_repository.get_goals()