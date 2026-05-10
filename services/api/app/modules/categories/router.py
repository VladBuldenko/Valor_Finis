from fastapi import APIRouter, status

from app.modules.categories import service
from app.modules.categories.schemas import CategoryResponse


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# Returns all available expense categories through the API.
# This function exists to expose default expense categories to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of CategoryResponse objects.
@router.get(
    "",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
)
def get_categories() -> list[CategoryResponse]:
    return service.get_categories()