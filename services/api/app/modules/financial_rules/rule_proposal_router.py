from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_rules import rule_proposal_service
from app.modules.financial_rules.rule_execution_schemas import (
    RuleProposalListResponse,
    RuleProposalResponse,
)

router = APIRouter(
    prefix="/rule-proposals",
    tags=["rule-proposals"],
)


@router.get("", response_model=RuleProposalListResponse, status_code=status.HTTP_200_OK)
def get_rule_proposals(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    proposal_status: Optional[
        Literal["awaiting_confirmation", "executed", "executed_partial", "rejected", "expired", "cancelled"]
    ] = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_proposal_service.list_proposals(
        db_session=db_session, user_id=current_user.id, limit=limit, offset=offset,
        status=proposal_status,
    )


@router.get("/{proposal_id}", response_model=RuleProposalResponse, status_code=status.HTTP_200_OK)
def get_rule_proposal(
    proposal_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_proposal_service.get_proposal(
        db_session=db_session, proposal_id=proposal_id, user_id=current_user.id,
    )


@router.post("/{proposal_id}/confirm", response_model=RuleProposalResponse, status_code=status.HTTP_200_OK)
def confirm_rule_proposal(
    proposal_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_proposal_service.confirm_proposal(
        db_session=db_session, proposal_id=proposal_id, user_id=current_user.id,
    )


@router.post("/{proposal_id}/reject", response_model=RuleProposalResponse, status_code=status.HTTP_200_OK)
def reject_rule_proposal(
    proposal_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_proposal_service.reject_proposal(
        db_session=db_session, proposal_id=proposal_id, user_id=current_user.id,
    )
