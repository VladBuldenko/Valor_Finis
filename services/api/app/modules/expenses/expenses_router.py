from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import (
    ExpenseCreate,
    ExpensePageResponse,
    ExpenseResponse,
    ExpenseUpdate,
)


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "A new expense was created.",
        },
        status.HTTP_200_OK: {
            "model": ExpenseResponse,
            "description": (
                "Idempotent replay: client_request_id already identifies an "
                "expense created from the same request; its current state is "
                "returned and nothing new is created."
            ),
        },
    },
)
def create_expense(
    expense_data: ExpenseCreate,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ExpenseResponse:
    """
    Creates a new expense.

    What:
        Handles POST /expenses HTTP requests.

    Why:
        Keeps HTTP request handling in the router layer and delegates
        business logic to the service layer.

    Parameters:
        expense_data: Validated request body for creating an expense.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        ExpenseResponse with the saved expense data (201), or with the
        existing record's current data for an idempotent replay (200).

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    result = expenses_service.create_or_replay_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=current_user.id,
    )

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return result.expense


@router.get(
    "",
    response_model=Union[ExpensePageResponse, list[ExpenseResponse]],
    status_code=status.HTTP_200_OK,
)
def get_expenses(
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
            "Opt-in pagination: number of expenses to skip. Sent alone, "
            "the page size is %d." % DEFAULT_PAGE_LIMIT
        ),
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> Union[ExpensePageResponse, list[ExpenseResponse]]:
    """
    Returns expenses for the authenticated user.

    What:
        Handles GET /expenses HTTP requests.

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
        Without limit and offset: the complete list of ExpenseResponse
        objects, newest expense_date first (unchanged behavior). With
        either: an ExpensePageResponse envelope (items, total, limit,
        offset) in the same order. Both only contain the authenticated
        user's expenses.
    """

    if limit is None and offset is None:
        return expenses_service.get_expenses(
            db_session=db_session,
            user_id=current_user.id,
        )

    return expenses_service.get_expenses_page(
        db_session=db_session,
        user_id=current_user.id,
        limit=DEFAULT_PAGE_LIMIT if limit is None else limit,
        offset=0 if offset is None else offset,
    )


@router.get(
    "/{expense_id}",
    response_model=ExpenseResponse,
    status_code=status.HTTP_200_OK,
)
def get_expense(
    expense_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ExpenseResponse:
    """
    Returns one expense of the authenticated user.

    What:
        Handles GET /expenses/{expense_id} HTTP requests.

    Why:
        The detail/edit screen opens a single expense, including one that is
        far down a paginated list, without downloading the whole history.

    Parameters:
        expense_id: Expense identifier from the path.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        ExpenseResponse of the expense.

    Raises:
        ExpenseNotFoundError (404) when the expense does not exist or belongs
        to another user; the two cases are indistinguishable.
    """

    return expenses_service.get_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=current_user.id,
    )


@router.patch(
    "/{expense_id}",
    response_model=ExpenseResponse,
    status_code=status.HTTP_200_OK,
)
def update_expense(
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ExpenseResponse:
    """
    Updates an existing expense.

    What:
        Handles PATCH /expenses/{expense_id} HTTP requests.

    Why:
        Allows the authenticated user to update only selected expense fields
        while keeping ownership validation inside the backend.

    Parameters:
        expense_id: Expense identifier from the path.
        expense_data: Validated partial request body for updating an expense.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        ExpenseResponse with the updated expense data.

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    return expenses_service.update_expense(
        db_session=db_session,
        expense_id=expense_id,
        expense_data=expense_data,
        user_id=current_user.id,
    )


@router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_expense(
    expense_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    """
    Deletes an existing expense.

    What:
        Handles DELETE /expenses/{expense_id} HTTP requests.

    Why:
        Allows the authenticated user to delete their own expense while
        preventing access to expenses owned by other users.

    Parameters:
        expense_id: Expense identifier from the path.
        current_user: Authenticated user resolved from request authentication data.
        db_session: Active SQLAlchemy database session provided by FastAPI.

    Returns:
        None.

    Raises:
        Domain exceptions propagated to the global exception handlers.
    """

    expenses_service.delete_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=current_user.id,
    )