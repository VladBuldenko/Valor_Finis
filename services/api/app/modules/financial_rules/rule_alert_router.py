from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_rules import rule_alert_service
from app.modules.financial_rules.rule_alert_schemas import (
    RuleAlertListResponse,
    RuleAlertResponse,
)

router = APIRouter(
    prefix="/rule-alerts",
    tags=["rule-alerts"],
)


@router.get("", response_model=RuleAlertListResponse, status_code=status.HTTP_200_OK)
def get_rule_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    acknowledged: Optional[bool] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_alert_service.list_alerts(
        db_session=db_session, user_id=current_user.id, limit=limit, offset=offset,
        acknowledged=acknowledged,
    )


@router.post("/{alert_id}/acknowledge", response_model=RuleAlertResponse, status_code=status.HTTP_200_OK)
def acknowledge_rule_alert(
    alert_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return rule_alert_service.acknowledge_alert(
        db_session=db_session, alert_id=alert_id, user_id=current_user.id,
    )
