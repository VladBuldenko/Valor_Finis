from app.modules.categories import repository
from app.modules.categories.schemas import CategoryResponse


# Returns all available expense categories.
# This function exists to keep business logic separate from API and storage layers.
# Parameters:
# - None.
# Returns:
# - List of CategoryResponse objects.
def get_categories() -> list[CategoryResponse]:
    return repository.get_categories()