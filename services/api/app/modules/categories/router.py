from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query, status

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.categories import service
from app.modules.categories.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# Creates a new category through the API.
# This function exists to receive validated HTTP input
# and delegate category creation to the service layer.
# Parameters:
# - category_data: validated request body containing category data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - CategoryResponse containing the saved category.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    category_data: CategoryCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> CategoryResponse:
    return service.create_category(
        db_session=db_session,
        category_data=category_data,
        user_id=current_user.id,
    )


# Returns categories through the API.
# This function exists to receive authenticated HTTP requests
# and delegate category retrieval to the service layer.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of CategoryResponse objects that belong to the authenticated user.
@router.get(
    "",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
)
def get_categories(
    include_hidden: bool = Query(
        default=False,
        description="Include categories hidden by the authenticated user.",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[CategoryResponse]:
    return service.get_categories(
        db_session=db_session,
        user_id=current_user.id,
        include_hidden=include_hidden,
    )

# Returns one category through the API.
# This function exists to retrieve a single category
# that belongs to the authenticated user.
# Parameters:
# - category_id: category identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - CategoryResponse object that belongs to the authenticated user.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
)
def get_category_by_id(
    category_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> CategoryResponse:
    return service.get_category_by_id(
        db_session=db_session,
        category_id=category_id,
        user_id=current_user.id,
    )


# Updates one category through the API.
# This function exists to receive partial category updates
# and delegate ownership-aware update logic to the service layer.
# Parameters:
# - category_id: category identifier from the URL path.
# - category_data: validated request body containing category update data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - Updated CategoryResponse object.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
)
def update_category(
    category_id: UUID,
    category_data: CategoryUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> CategoryResponse:
    return service.update_category(
        db_session=db_session,
        category_id=category_id,
        category_data=category_data,
        user_id=current_user.id,
    )


# Deletes one category through the API.
# This function exists to delete a category
# that belongs to the authenticated user.
# Parameters:
# - category_id: category identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None. The API returns HTTP 204 when the category is deleted.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_category(
    category_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    service.delete_category(
        db_session=db_session,
        category_id=category_id,
        user_id=current_user.id,
    )