from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.categories import repository
from app.modules.categories.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)


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


# Returns categories for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter categories.
# Returns:
# - List of CategoryResponse objects.
def get_categories(
    db_session: Session,
    user_id: UUID,
) -> list[CategoryResponse]:
    category_models = repository.get_categories(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        CategoryResponse.model_validate(category_model)
        for category_model in category_models
    ]


# Returns one category owned by the authenticated user.
# This function exists to keep ownership-aware read logic outside the router layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - CategoryResponse object.
def get_category_by_id(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> CategoryResponse:
    category_model = repository.get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )

    return CategoryResponse.model_validate(category_model)


# Updates one category owned by the authenticated user.
# This function exists to keep category update business flow outside the router layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - category_data: validated category update data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - Updated CategoryResponse object.
def update_category(
    db_session: Session,
    category_id: UUID,
    category_data: CategoryUpdate,
    user_id: UUID,
) -> CategoryResponse:
    category_model = repository.update_category(
        db_session=db_session,
        category_id=category_id,
        category_data=category_data,
        user_id=user_id,
    )

    return CategoryResponse.model_validate(category_model)


# Deletes one category owned by the authenticated user.
# This function exists to keep category deletion business flow outside the router layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - None.
def delete_category(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> None:
    repository.delete_category(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )