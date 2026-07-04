from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.categories import service
from app.modules.categories.schemas import CategoryCreate, CategoryResponse
from app.modules.categories.errors import CategoryAlreadyExistsError


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# Creates a new category through the API.
# This function exists to receive validated HTTP input
# and delegate category creation to the service layer.
# Parameters:
# - category_data: validated request body containing category data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - CategoryResponse containing the saved category.
@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    category_data: CategoryCreate,
    db_session: Session = Depends(get_db_session),
) -> CategoryResponse:
    try:
        return service.create_category(
            db_session=db_session,
            category_data=category_data,
        )
    except CategoryAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category with this name already exists for this user.",
        ) from error


# Returns categories through the API.
# This function exists to receive HTTP filtering parameters
# and delegate category retrieval to the service layer.
# Parameters:
# - user_id: optional query parameter used to filter categories by owner.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of CategoryResponse objects.
@router.get(
    "",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
)
def get_categories(
    user_id: Optional[UUID] = Query(
        default=None,
        description="Filter categories by user identifier.",
    ),
    db_session: Session = Depends(get_db_session),
) -> list[CategoryResponse]:
    return service.get_categories(
        db_session=db_session,
        user_id=user_id,
    )