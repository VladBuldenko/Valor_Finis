from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.categories import repository
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryDefaultDeletionNotAllowedError,
    CategoryDefaultModificationNotAllowedError,
)
from app.modules.categories.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)


# Creates a new category using validated input data and authenticated user id.
# This function exists to enforce category name uniqueness
# before delegating persistence to the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_data: validated category creation data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - CategoryResponse created from the saved database model.
# Raises:
# - CategoryAlreadyExistsError when the user already has
#   a category with the same case-insensitive name.
def create_category(
    db_session: Session,
    category_data: CategoryCreate,
    user_id: UUID,
) -> CategoryResponse:
    repository.ensure_default_categories(
        db_session=db_session,
        user_id=user_id,
    )

    category_model = repository.create_category(
        db_session=db_session,
        category_data=category_data,
        user_id=user_id,
    )

    return CategoryResponse.model_validate(
        category_model
    )


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
    include_hidden: bool = False,
) -> list[CategoryResponse]:
    repository.ensure_default_categories(
        db_session=db_session,
        user_id=user_id,
    )

    category_models = repository.get_categories(
        db_session=db_session,
        user_id=user_id,
        include_hidden=include_hidden,
    )

    return [
        CategoryResponse.model_validate(category_model)
        for category_model in category_models
    ]


# Returns one category owned by the authenticated user.
# This function exists to keep ownership-aware read logic
# outside the router layer.
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
# This function exists to protect default categories
# and enforce case-insensitive category name uniqueness.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - category_data: validated category update data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - Updated CategoryResponse object.
# Raises:
# - CategoryDefaultModificationNotAllowedError when the category is default.
# - CategoryAlreadyExistsError when another category has the same name.
def update_category(
    db_session: Session,
    category_id: UUID,
    category_data: CategoryUpdate,
    user_id: UUID,
) -> CategoryResponse:
    existing_category = repository.get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )

    if existing_category.is_default:
        disallowed_fields = (
            field_name
            for field_name in category_data.model_fields_set
            if field_name != "is_visible"
        )

        if any(disallowed_fields):
            raise CategoryDefaultModificationNotAllowedError()

    if (
        category_data.name is not None
        and repository.category_name_exists(
            db_session=db_session,
            user_id=user_id,
            category_name=category_data.name,
            excluded_category_id=category_id,
        )
    ):
        raise CategoryAlreadyExistsError()

    updated_category = repository.update_category(
        db_session=db_session,
        category_id=category_id,
        category_data=category_data,
        user_id=user_id,
    )

    return CategoryResponse.model_validate(updated_category)


# Deletes one category owned by the authenticated user.
# This function exists to protect default categories
# while allowing custom category deletion.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - None.
# Raises:
# - CategoryDefaultDeletionNotAllowedError when the category is default.
def delete_category(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> None:
    existing_category = repository.get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )

    if existing_category.is_default:
        raise CategoryDefaultDeletionNotAllowedError()

    repository.delete_category(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )