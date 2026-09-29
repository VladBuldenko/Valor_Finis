from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.accounts import account_transfer_service
from app.modules.accounts.account_transfer_schemas import (
    AccountTransferCreate,
    AccountTransferResponse,
)

# VF-018C public Transfer API. Manual posting (POST /{id}/post, VF-018D),
# PATCH, and GET by id are intentionally absent.
router = APIRouter(
    prefix="/account-transfers",
    tags=["Account Transfers"],
)


# Creates an AccountTransfer through the API, idempotently.
# This function exists to receive validated HTTP input and translate the
# service's create-or-replay outcome into the HTTP status: 201 when this
# request created the transfer, 200 when client_request_id identifies a
# transfer already created from the same payload (its current state is
# returned). The same key with a different payload is a 409 raised by the
# service and mapped centrally.
# Parameters:
# - transfer_data: validated request body.
# - response: FastAPI response, used only to downgrade 201 to 200 on replay.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - AccountTransferResponse with the transfer's current state.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "",
    response_model=AccountTransferResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "A new transfer was created (planned or immediately posted).",
        },
        status.HTTP_200_OK: {
            "model": AccountTransferResponse,
            "description": (
                "Idempotent replay: client_request_id already identifies a "
                "transfer created from the same payload; its current state is "
                "returned and nothing new is created."
            ),
        },
    },
)
def create_account_transfer(
    transfer_data: AccountTransferCreate,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountTransferResponse:
    result = account_transfer_service.create_account_transfer(
        db_session=db_session,
        transfer_data=transfer_data,
        user_id=current_user.id,
    )

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return result.transfer


# Returns the authenticated user's transfers through the API.
# This function exists to receive authenticated HTTP requests and delegate
# retrieval to the service layer. Planned and posted transfers are both
# returned; there is no GET-by-id endpoint (clients resolve a single
# transfer from this list, matching the Accounts/Goals pattern).
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of AccountTransferResponse objects, newest first.
@router.get(
    "",
    response_model=list[AccountTransferResponse],
    status_code=status.HTTP_200_OK,
)
def get_account_transfers(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[AccountTransferResponse]:
    return account_transfer_service.get_account_transfers(
        db_session=db_session,
        user_id=current_user.id,
    )


# Hard-deletes a transfer through the API.
# This function exists to receive authenticated delete requests and
# delegate deletion to the service layer. Another user's transfer behaves
# as not found (404).
# Parameters:
# - transfer_id: transfer identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{transfer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_account_transfer(
    transfer_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    account_transfer_service.delete_account_transfer(
        db_session=db_session,
        transfer_id=transfer_id,
        user_id=current_user.id,
    )
