from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.accounts import account_service
from app.modules.accounts.account_schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)
from app.modules.accounts.account_transaction_schemas import (
    AccountTransactionCreate,
    AccountTransactionResponse,
)


router = APIRouter(
    prefix="/accounts",
    tags=["Accounts"],
)


# Creates a new account through the API.
# This function exists to receive validated HTTP input
# and delegate account creation to the service layer.
# Parameters:
# - account_data: validated request body containing account data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - AccountResponse containing the saved account.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    account_data: AccountCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountResponse:
    return account_service.create_account(
        db_session=db_session,
        account_data=account_data,
        user_id=current_user.id,
    )


# Returns accounts through the API.
# This function exists to receive authenticated HTTP requests
# and delegate account retrieval to the service layer. There is no
# GET /accounts/{id} endpoint - mobile detail screens resolve a single
# account from this list response, matching the established Goals
# pattern.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of AccountResponse objects that belong to the authenticated user.
@router.get(
    "",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
)
def get_accounts(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[AccountResponse]:
    return account_service.get_accounts(
        db_session=db_session,
        user_id=current_user.id,
    )


# Updates an existing account through the API.
# This function exists to receive partial HTTP update input
# and delegate account update logic to the service layer.
# Parameters:
# - account_id: account identifier from the URL path.
# - account_data: validated partial request body containing updated account data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - AccountResponse containing the updated account.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
)
def update_account(
    account_id: UUID,
    account_data: AccountUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountResponse:
    return account_service.update_account(
        db_session=db_session,
        account_id=account_id,
        account_data=account_data,
        user_id=current_user.id,
    )


# Deletes an existing account through the API.
# This function exists to receive authenticated delete requests
# and delegate account deletion to the service layer.
# Parameters:
# - account_id: account identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_account(
    account_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    account_service.delete_account(
        db_session=db_session,
        account_id=account_id,
        user_id=current_user.id,
    )


# Creates a manual adjustment transaction for an account through the API.
# This function exists to receive validated HTTP input and delegate the
# atomic ledger write to the service layer. opening_balance is
# unreachable here - AccountTransactionCreate has no kind field at all,
# the service always creates kind="adjustment" for this endpoint.
# Parameters:
# - account_id: account identifier from the URL path.
# - transaction_data: validated request body containing adjustment data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - AccountTransactionResponse containing the saved transaction.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "/{account_id}/transactions",
    response_model=AccountTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account_transaction(
    account_id: UUID,
    transaction_data: AccountTransactionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountTransactionResponse:
    return account_service.create_account_transaction(
        db_session=db_session,
        account_id=account_id,
        transaction_data=transaction_data,
        user_id=current_user.id,
    )


# Returns an account's full transaction history through the API.
# This function exists to receive authenticated HTTP requests and delegate
# transaction history retrieval to the service layer. Another user's
# Account behaves as not found, never leaking whether it exists.
# Parameters:
# - account_id: account identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of AccountTransactionResponse objects, newest first.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.get(
    "/{account_id}/transactions",
    response_model=list[AccountTransactionResponse],
    status_code=status.HTTP_200_OK,
)
def get_account_transactions(
    account_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[AccountTransactionResponse]:
    return account_service.get_account_transactions(
        db_session=db_session,
        account_id=account_id,
        user_id=current_user.id,
    )
