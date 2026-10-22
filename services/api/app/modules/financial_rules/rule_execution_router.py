from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_rules import rule_execution_service
from app.modules.financial_rules.rule_execution_schemas import RuleExecutionListResponse

router = APIRouter(
    prefix="/rule-executions",
    tags=["rule-executions"],
)


@router.get(
    "",
    response_model=RuleExecutionListResponse,
    status_code=status.HTTP_200_OK,
)
def get_rule_executions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    rule_id: Optional[UUID] = None,
    execution_status: Optional[
        Literal[
            "awaiting_confirmation", "executed", "executed_partial", "skipped",
            "blocked", "rejected", "expired", "cancelled",
        ]
    ] = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_execution_service.list_executions(
        db_session=db_session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        rule_id=rule_id,
        status=execution_status,
    )
