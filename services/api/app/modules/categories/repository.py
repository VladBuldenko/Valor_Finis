from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.categories.category_models import CategoryModel
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryNotFoundError,
)
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate


# Creates and saves a new category database record.
# This function exists to isolate PostgreSQL write operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_data: validated category creation data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - CategoryModel instance saved in PostgreSQL.
# Raises:
# - CategoryAlreadyExistsError: when the same user already has a category with this name.
def create_category(
    db_session: Session,
    category_data: CategoryCreate,
    user_id: UUID,
) -> CategoryModel:
    category_model = CategoryModel(
        user_id=user_id,
        name=category_data.name,
        color=category_data.color,
        icon=category_data.icon,
        is_default=False,
    )

    db_session.add(category_model)

    try:
        db_session.commit()
    except IntegrityError as error:
        db_session.rollback()

        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == "uq_categories_user_id_name":
            raise CategoryAlreadyExistsError from error

        raise

    db_session.refresh(category_model)

    return category_model


# Returns category database records.
# This function exists to isolate PostgreSQL read operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter categories.
# Returns:
# - List of CategoryModel instances from the database.
def get_categories(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[CategoryModel]:
    query = db_session.query(CategoryModel)

    if user_id is not None:
        query = query.filter(CategoryModel.user_id == user_id)

    return query.order_by(CategoryModel.name.asc()).all()


# Returns one category by category id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - CategoryModel instance from the database.
# Raises:
# - CategoryNotFoundError: when category does not exist or does not belong to the user.
def get_category_by_id(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> CategoryModel:
    category_model = (
        db_session.query(CategoryModel)
        .filter(
            CategoryModel.id == category_id,
            CategoryModel.user_id == user_id,
        )
        .first()
    )

    if category_model is None:
        raise CategoryNotFoundError()

    return category_model


# Updates an existing category owned by the authenticated user.
# This function exists to isolate PostgreSQL update operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - category_data: validated category update data.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - Updated CategoryModel instance.
# Raises:
# - CategoryNotFoundError: when category does not exist or does not belong to the user.
# - CategoryAlreadyExistsError: when the same user already has a category with this name.
def update_category(
    db_session: Session,
    category_id: UUID,
    category_data: CategoryUpdate,
    user_id: UUID,
) -> CategoryModel:
    category_model = get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )

    update_data = category_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(category_model, field_name, field_value)

    try:
        db_session.commit()
    except IntegrityError as error:
        db_session.rollback()

        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == "uq_categories_user_id_name":
            raise CategoryAlreadyExistsError from error

        raise

    db_session.refresh(category_model)

    return category_model


# Deletes an existing category owned by the authenticated user.
# This function exists to isolate PostgreSQL delete operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier.
# - user_id: authenticated user identifier that owns the category.
# Returns:
# - None.
# Raises:
# - CategoryNotFoundError: when category does not exist or does not belong to the user.
def delete_category(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> None:
    category_model = get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=user_id,
    )

    db_session.delete(category_model)
    db_session.commit()