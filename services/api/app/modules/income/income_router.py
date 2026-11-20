from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_events import financial_event_processor
from app.modules.income import income_service
from app.modules.income.income_schemas import (
    IncomeCreate,
    IncomePageResponse,
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
    responses={
        status.HTTP_201_CREATED: {
            "description": "A new income record was created.",
        },
        status.HTTP_200_OK: {
            "model": IncomeResponse,
            "description": (
                "Idempotent replay: client_request_id already identifies an "
                "income created from the same request; its current state is "
                "returned and nothing new is created."
            ),
        },
    },
)
def create_income(
    background_tasks: BackgroundTasks,
    income_data: IncomeCreate,
    response: Response,
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
        IncomeResponse with the saved income data (201), or with the
        existing record's current data for an idempotent replay (200).

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    result = income_service.create_or_replay_income(
        db_session=db_session,
        income_data=income_data,
        user_id=current_user.id,
    )

    if not result.created:
        # A replay created nothing: no event exists to dispatch.
        response.status_code = status.HTTP_200_OK

        return result.income

    # Runs after the response is sent; the committed event is already durable.
    background_tasks.add_task(
        financial_event_processor.dispatch_user_events_best_effort, current_user.id,
    )

    return result.income


@router.get(
    "",
    response_model=Union[IncomePageResponse, list[IncomeResponse]],
    status_code=status.HTTP_200_OK,
)
def get_income(
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description=(
            "Opt-in pagination: page size (1-%d). When limit or offset is "
            "sent the response is a page envelope; with neither, the "
            "complete bare list is returned as before." % MAX_PAGE_LIMIT
        ),
    ),
    offset: Optional[int] = Query(
        default=None,
        ge=0,
        description=(
            "Opt-in pagination: number of income records to skip. Sent "
            "alone, the page size is %d." % DEFAULT_PAGE_LIMIT
        ),
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> Union[IncomePageResponse, list[IncomeResponse]]:
    """
    Returns income records for the authenticated user.

    What:
        Handles GET /income HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        data retrieval to the service layer. Pagination is opt-in so the
        response shape the shipped client relies on never changes under it.

    Parameters:
        limit: optional page size; requesting pagination when present.
        offset: optional number of records to skip; requesting pagination
            when present.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        Without limit and offset: the complete list of IncomeResponse
        objects, newest received_at first (unchanged behavior). With
        either: an IncomePageResponse envelope (items, total, limit,
        offset) in the same order. Both only contain the authenticated
        user's income records.
    """

    if limit is None and offset is None:
        return income_service.get_income(
            db_session=db_session,
            user_id=current_user.id,
        )

    return income_service.get_income_page(
        db_session=db_session,
        user_id=current_user.id,
        limit=DEFAULT_PAGE_LIMIT if limit is None else limit,
        offset=0 if offset is None else offset,
    )


@router.get(
    "/{income_id}",
    response_model=IncomeResponse,
    status_code=status.HTTP_200_OK,
)
def get_income_record(
    income_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> IncomeResponse:
    """
    Returns one income record of the authenticated user.

    What:
        Handles GET /income/{income_id} HTTP requests.

    Why:
        The edit screen opens a single income record, including one that is
        far down a paginated list, without downloading the whole history.

    Parameters:
        income_id: Income identifier from the path.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        IncomeResponse of the income record.

    Raises:
        IncomeNotFoundError (404) when the record does not exist or belongs
        to another user; the two cases are indistinguishable.
    """

    return income_service.get_income_by_id(
        db_session=db_session,
        income_id=income_id,
        user_id=current_user.id,
    )


@router.patch(
    "/{income_id}",
    response_model=IncomeResponse,
    status_code=status.HTTP_200_OK,
)
def update_income(
    background_tasks: BackgroundTasks,
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

    updated = income_service.update_income(
        db_session=db_session,
        income_id=income_id,
        income_data=income_data,
        user_id=current_user.id,
    )
    background_tasks.add_task(
        financial_event_processor.dispatch_user_events_best_effort, current_user.id,
    )

    return updated


@router.delete(
    "/{income_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_income(
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        financial_event_processor.dispatch_user_events_best_effort, current_user.id,
    )
