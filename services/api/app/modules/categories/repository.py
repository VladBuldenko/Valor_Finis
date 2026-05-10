from app.modules.categories.schemas import CategoryResponse


DEFAULT_CATEGORIES: list[CategoryResponse] = [
    CategoryResponse(key="food", name="Food"),
    CategoryResponse(key="clothing", name="Clothing"),
    CategoryResponse(key="car", name="Car"),
    CategoryResponse(key="cafe", name="Cafe"),
    CategoryResponse(key="home", name="Home"),
    CategoryResponse(key="health", name="Health"),
    CategoryResponse(key="subscriptions", name="Subscriptions"),
    CategoryResponse(key="other", name="Other"),
]


# Returns the default list of expense categories.
# This function exists to keep category storage logic inside the repository layer.
# Parameters:
# - None.
# Returns:
# - List of CategoryResponse objects.
def get_categories() -> list[CategoryResponse]:
    return DEFAULT_CATEGORIES