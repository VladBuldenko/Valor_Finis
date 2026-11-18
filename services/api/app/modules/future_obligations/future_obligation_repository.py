from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.future_obligations.future_obligation_errors import (
    FutureObligationClientRequestIdTakenError,
)
from app.modules.future_obligations.future_obligation_models import FutureObligationModel
from app.modules.future_obligations.future_obligation_schemas import FutureObligationCreate

CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT = "uq_future_obligations_user_id_client_request_id"


# Inserts a future obligation owned by `user_id`.
# This function exists to keep persistence out of the service. user_id comes from
# authentication, never from the request body. The caller commits (commit=False
# flushes only), so the insert and the idempotency key are one atomic unit.
# Parameters:
# - data: the validated create request; `currency` must already be resolved.
# - client_request_id / client_request_fingerprint: set together or both None.
# Raises:
# - FutureObligationClientRequestIdTakenError: the per-user key already exists
#   (a concurrent create committed first).
def create_obligation(
    db_session: Session,
    data: FutureObligationCreate,
    currency: str,
    user_id: UUID,
    commit: bool = False,
    client_request_fingerprint: Optional[str] = None,
) -> FutureObligationModel:
    obligation = FutureObligationModel(
        user_id=user_id,
        name=data.name,
        description=data.description,
        schedule=data.schedule,
        amount=data.amount,
        currency=currency,
        first_due_date=data.first_due_date,
        final_due_date=data.final_due_date,
        status="active",
        client_request_id=data.client_request_id,
        client_request_fingerprint=client_request_fingerprint,
    )

    db_session.add(obligation)

    try:
        if commit:
            db_session.commit()
        else:
            db_session.flush()
    except IntegrityError as error:
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)

        if constraint_name == CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT:
            raise FutureObligationClientRequestIdTakenError() from error

        raise

    db_session.refresh(obligation)

    return obligation


# Returns the user's obligation created with a given client request id, if any.
def get_by_client_request_id(
    db_session: Session,
    user_id: UUID,
    client_request_id: UUID,
) -> Optional[FutureObligationModel]:
    return (
        db_session.query(FutureObligationModel)
        .filter(
            FutureObligationModel.user_id == user_id,
            FutureObligationModel.client_request_id == client_request_id,
        )
        .first()
    )


# Returns one obligation of the user, or None. A foreign obligation is None too,
# so a caller can never tell "not yours" from "does not exist".
def get_by_id(
    db_session: Session,
    obligation_id: UUID,
    user_id: UUID,
) -> Optional[FutureObligationModel]:
    return (
        db_session.query(FutureObligationModel)
        .filter(
            FutureObligationModel.id == obligation_id,
            FutureObligationModel.user_id == user_id,
        )
        .first()
    )


# Same as get_by_id but locks the row (SELECT ... FOR UPDATE), so two updates of
# one obligation run one after the other.
def get_by_id_for_update(
    db_session: Session,
    obligation_id: UUID,
    user_id: UUID,
) -> Optional[FutureObligationModel]:
    return (
        db_session.query(FutureObligationModel)
        .filter(
            FutureObligationModel.id == obligation_id,
            FutureObligationModel.user_id == user_id,
        )
        .with_for_update()
        .first()
    )


# Returns every obligation of the user (one query), in a deterministic order.
def list_for_user(db_session: Session, user_id: UUID) -> list[FutureObligationModel]:
    return (
        db_session.query(FutureObligationModel)
        .filter(FutureObligationModel.user_id == user_id)
        .order_by(
            FutureObligationModel.first_due_date.asc(),
            FutureObligationModel.created_at.asc(),
            FutureObligationModel.id.asc(),
        )
        .all()
    )


# Returns the user's ACTIVE obligations that can have a due date in the window
# [as_of, window_end] (one query), so the projection never reads rows that
# cannot contribute: archived ones, obligations that start after the window, a
# one-time obligation already due before today and a monthly one that ended
# before today.
def list_active_for_projection(
    db_session: Session,
    user_id: UUID,
    as_of: date,
    window_end: date,
) -> list[FutureObligationModel]:
    return (
        db_session.query(FutureObligationModel)
        .filter(
            FutureObligationModel.user_id == user_id,
            FutureObligationModel.status == "active",
            FutureObligationModel.first_due_date <= window_end,
            or_(
                and_(
                    FutureObligationModel.schedule == "one_time",
                    FutureObligationModel.first_due_date >= as_of,
                ),
                and_(
                    FutureObligationModel.schedule == "monthly",
                    or_(
                        FutureObligationModel.final_due_date.is_(None),
                        FutureObligationModel.final_due_date >= as_of,
                    ),
                ),
            ),
        )
        .order_by(FutureObligationModel.first_due_date.asc(), FutureObligationModel.id.asc())
        .all()
    )


# Counts the user's ACTIVE obligations.
def count_active_for_user(db_session: Session, user_id: UUID) -> int:
    return (
        db_session.query(func.count(FutureObligationModel.id))
        .filter(
            FutureObligationModel.user_id == user_id,
            FutureObligationModel.status == "active",
        )
        .scalar()
        or 0
    )
