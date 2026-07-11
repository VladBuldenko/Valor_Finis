from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.categories.category_models import CategoryModel
from app.modules.categories.errors import CategoryAlreadyExistsError
from app.modules.categories.schemas import CategoryCreate


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
        is_default=category_data.is_default,
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