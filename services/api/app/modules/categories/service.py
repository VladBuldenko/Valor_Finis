from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.categories import repository
from app.modules.categories.schemas import CategoryCreate, CategoryResponse


# Creates a new category using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_data: validated category creation data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - CategoryResponse created from the saved database model.
def create_category(
    db_session: Session,
    category_data: CategoryCreate,
    user_id: UUID,
) -> CategoryResponse:
    category_model = repository.create_category(
        db_session=db_session,
        category_data=category_data,
        user_id=user_id,
    )

    return CategoryResponse.model_validate(category_model)


# Returns categories for a user or all categories when user_id is not provided.
# This function exists to map database models to public API responses
# and provide a place for future category business rules.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter categories.
# Returns:
# - List of CategoryResponse objects.
def get_categories(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[CategoryResponse]:
    category_models = repository.get_categories(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        CategoryResponse.model_validate(category_model)
        for category_model in category_models
    ]