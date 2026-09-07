from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.categories.category_models import CategoryModel
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryNotFoundError,
)
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate
from app.modules.categories.default_categories import DEFAULT_CATEGORIES

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
        if constraint_name in {
            "uq_categories_user_id_name",
            "uq_categories_user_id_name_lower",
        }:
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
    include_hidden: bool = True,
) -> list[CategoryModel]:
    query = db_session.query(CategoryModel)

    if user_id is not None:
        query = query.filter(
            CategoryModel.user_id == user_id,
        )

    if not include_hidden:
        query = query.filter(
            CategoryModel.is_visible.is_(True),
        )

    return query.order_by(CategoryModel.name.asc()).all()

# Checks whether a user already has a category with the same normalized name.
# This function exists to enforce case-insensitive category name uniqueness
# before create and update operations.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the categories.
# - category_name: normalized category name being checked.
# - excluded_category_id: optional category identifier excluded during updates.
# Returns:
# - True when another matching category exists, otherwise False.
def category_name_exists(
    db_session: Session,
    user_id: UUID,
    category_name: str,
    excluded_category_id: Optional[UUID] = None,
) -> bool:
    query = (
        db_session.query(CategoryModel.id)
        .filter(
            CategoryModel.user_id == user_id,
            func.lower(CategoryModel.name) == category_name.lower(),
        )
    )

    if excluded_category_id is not None:
        query = query.filter(
            CategoryModel.id != excluded_category_id,
        )

    return query.first() is not None


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

        if constraint_name in {
            "uq_categories_user_id_name",
            "uq_categories_user_id_name_lower",
        }:
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

def ensure_default_categories(
    db_session: Session,
    user_id: UUID,
) -> None:
    """
    Ensures that a user has all predefined categories.

    Existing user categories with matching predefined names are promoted
    to default categories so historical category IDs and relationships
    are preserved.
    """

    existing_categories = (
        db_session.query(CategoryModel)
        .filter(CategoryModel.user_id == user_id)
        .all()
    )

    categories_by_system_key = {
        category.system_key: category
        for category in existing_categories
        if category.system_key is not None
    }

    categories_by_name = {
        category.name.casefold(): category
        for category in existing_categories
    }

    has_changes = False
    rows_to_insert: list[dict] = []

    for default_category in DEFAULT_CATEGORIES:
        system_key = default_category["system_key"]
        name = default_category["name"]

        if system_key in categories_by_system_key:
            continue

        existing_category = categories_by_name.get(
            name.casefold()
        )

        if existing_category is not None:
            existing_category.system_key = system_key
            existing_category.is_default = True

            categories_by_system_key[system_key] = (
                existing_category
            )

            has_changes = True
            continue

        rows_to_insert.append(
            {
                "id": uuid4(),
                "user_id": user_id,
                "name": name,
                "system_key": system_key,
                "color": None,
                "icon": None,
                "is_default": True,
                "is_visible": True,
            }
        )

        has_changes = True

    if not has_changes:
        return

    # Target-less ON CONFLICT DO NOTHING skips a conflicting row regardless
    # of which unique index (system_key or case-insensitive name) it hits,
    # so two concurrent first-use bootstraps can't raise IntegrityError here.
    if rows_to_insert:
        db_session.execute(
            pg_insert(CategoryModel)
            .values(rows_to_insert)
            .on_conflict_do_nothing()
        )

    db_session.commit()