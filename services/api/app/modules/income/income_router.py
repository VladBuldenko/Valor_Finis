from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.income import income_service
from app.modules.income.income_schemas import (
    IncomeCreate,
    IncomeResponse,
    IncomeUpdate,
)


router = APIRouter(
    prefix="/income",
    tags=["Income"],
)


@router.post(
    "",
    response_model=IncomeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_income(
    income_data: IncomeCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> IncomeResponse:
    """
    Creates a new income record.

    What:
        Handles POST /income HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        business logic to the service layer.

    Parameters:
        income_data: Validated request body for creating an income record.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        IncomeResponse with the saved income data.

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    return income_service.create_income(
        db_session=db_session,
        income_data=income_data,
        user_id=current_user.id,
    )


@router.get(
    "",
    response_model=list[IncomeResponse],
    status_code=status.HTTP_200_OK,
)
def get_income(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[IncomeResponse]:
    """
    Returns income records for the authenticated user.

    What:
        Handles GET /income HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        data retrieval to the service layer. There is no GET
        /income/{id} endpoint - mobile detail resolution, if ever needed,
        can resolve a single record from this list response, matching the
        established Goals/Accounts pattern.

    Parameters:
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        List of IncomeResponse objects that belong to the authenticated
        user, newest received_at first.
    """

    return income_service.get_income(
        db_session=db_session,
        user_id=current_user.id,
    )


@router.patch(
    "/{income_id}",
    response_model=IncomeResponse,
    status_code=status.HTTP_200_OK,
)
def update_income(
    income_id: UUID,
    income_data: IncomeUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> IncomeResponse:
    """
    Updates an existing income record.

    What:
        Handles PATCH /income/{income_id} HTTP requests.

    Why:
        Allows the authenticated user to update only selected income
        fields while keeping ownership validation inside the backend.

    Parameters:
        income_id: Income identifier from the path.
        income_data: Validated partial request body for updating an income record.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        IncomeResponse with the updated income data.

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    return income_service.update_income(
        db_session=db_session,
        income_id=income_id,
        income_data=income_data,
        user_id=current_user.id,
    )


@router.delete(
    "/{income_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_income(
    income_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    """
    Deletes an existing income record.

    What:
        Handles DELETE /income/{income_id} HTTP requests.

    Why:
        Allows the authenticated user to delete their own income record
        while preventing access to income records owned by other users.

    Parameters:
        income_id: Income identifier from the path.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        None.

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    income_service.delete_income(
        db_session=db_session,
        income_id=income_id,
        user_id=current_user.id,
    )
