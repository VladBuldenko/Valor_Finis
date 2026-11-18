from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.future_obligations import future_obligation_link_service, future_obligation_service
from app.modules.future_obligations.future_obligation_link_schemas import (
    OccurrenceCandidatesResponse,
    OccurrenceLinkCreate,
    OccurrenceLinkResponse,
    ReconciliationOverviewResponse,
)
from app.modules.future_obligations.future_obligation_schemas import (
    FutureObligationCreate,
    FutureObligationResponse,
    FutureObligationUpdate,
)
from app.modules.future_obligations.future_obligation_upcoming_schemas import (
    UpcomingObligationsResponse,
)

# Future obligations (VF-GOALS-PLANNING-002C1). Every route is authenticated and scoped
# to the caller's own obligations. None of them pays, reserves or records
# anything: an obligation is a forecast input the user typed in.

router = APIRouter(
    prefix="/future-obligations",
    tags=["Future obligations"],
)


# Records a future obligation (201), or replays an earlier identical create (200).
@router.post(
    "",
    response_model=FutureObligationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": FutureObligationResponse,
            "description": (
                "Idempotent replay: client_request_id already identifies an obligation "
                "created from the same request; its current state is returned and nothing "
                "new is created."
            ),
        },
    },
)
def create_future_obligation(
    data: FutureObligationCreate,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> FutureObligationResponse:
    result = future_obligation_service.create_or_replay_future_obligation(
        db_session=db_session,
        data=data,
        user_id=current_user.id,
    )

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return result.obligation


# Returns the caller's obligations: active ones by next due date, then archived.
@router.get(
    "",
    response_model=list[FutureObligationResponse],
    status_code=status.HTTP_200_OK,
)
def get_future_obligations(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[FutureObligationResponse]:
    return future_obligation_service.get_future_obligations(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns the upcoming-bills projection for the next 12 calendar months. Read-only.
# Declared BEFORE the dynamic "/{obligation_id}" routes so the static path can
# never be captured as an id.
@router.get(
    "/upcoming",
    response_model=UpcomingObligationsResponse,
    status_code=status.HTTP_200_OK,
)
def get_upcoming_obligations(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> UpcomingObligationsResponse:
    return future_obligation_service.get_upcoming_obligations(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns the bounded reconciliation overview: three previous months, the current
# month and the 12-month horizon, with each occurrence's link status. Read-only.
# Static path, declared BEFORE the dynamic "/{obligation_id}" routes.
@router.get(
    "/reconciliation",
    response_model=ReconciliationOverviewResponse,
    status_code=status.HTTP_200_OK,
)
def get_reconciliation_overview(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReconciliationOverviewResponse:
    return future_obligation_link_service.get_overview(
        db_session=db_session,
        user_id=current_user.id,
    )


@router.get(
    "/{obligation_id}",
    response_model=FutureObligationResponse,
    status_code=status.HTTP_200_OK,
)
def get_future_obligation(
    obligation_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> FutureObligationResponse:
    return future_obligation_service.get_future_obligation(
        db_session=db_session,
        obligation_id=obligation_id,
        user_id=current_user.id,
    )


# Updates, archives (status "archived") or restores (status "active") an obligation.
@router.patch(
    "/{obligation_id}",
    response_model=FutureObligationResponse,
    status_code=status.HTTP_200_OK,
)
def update_future_obligation(
    obligation_id: UUID,
    data: FutureObligationUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> FutureObligationResponse:
    return future_obligation_service.update_future_obligation(
        db_session=db_session,
        obligation_id=obligation_id,
        data=data,
        user_id=current_user.id,
    )


# Lists the Expenses the user may link to one occurrence (same currency, exact same
# amount, not linked yet, recorded on or before today), newest first, bounded, plus
# a count of the other Expenses that cannot be linked and why. Read-only; the user
# chooses, nothing is matched automatically.
@router.get(
    "/{obligation_id}/occurrence-candidates",
    response_model=OccurrenceCandidatesResponse,
    status_code=status.HTTP_200_OK,
)
def get_occurrence_candidates(
    obligation_id: UUID,
    due_date: date = Query(description="The occurrence's due date."),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> OccurrenceCandidatesResponse:
    return future_obligation_link_service.get_candidates(
        db_session=db_session,
        obligation_id=obligation_id,
        due_date=due_date,
        user_id=current_user.id,
    )


# Links one occurrence to an existing Expense (201), or returns the identical
# existing link (200). The link is relationship metadata: it creates no Expense,
# posts nothing to an Account, and does not verify a bank payment. An existing link
# is never replaced; remove it first.
@router.post(
    "/{obligation_id}/occurrence-links",
    response_model=OccurrenceLinkResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": OccurrenceLinkResponse,
            "description": "Idempotent replay: this occurrence is already linked to this Expense.",
        },
    },
)
def create_occurrence_link(
    obligation_id: UUID,
    data: OccurrenceLinkCreate,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> OccurrenceLinkResponse:
    result = future_obligation_link_service.create_or_replay_link(
        db_session=db_session,
        obligation_id=obligation_id,
        data=data,
        user_id=current_user.id,
    )

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return result.link


# Removes a link. The Expense and the obligation are not changed.
@router.delete(
    "/{obligation_id}/occurrence-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_occurrence_link(
    obligation_id: UUID,
    link_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    future_obligation_link_service.delete_link(
        db_session=db_session,
        obligation_id=obligation_id,
        link_id=link_id,
        user_id=current_user.id,
    )
