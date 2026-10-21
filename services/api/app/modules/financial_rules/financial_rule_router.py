from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_rules import financial_rule_service
from app.modules.financial_rules.financial_rule_schemas import (
    FinancialRuleCreate,
    FinancialRuleResponse,
    FinancialRuleUpdate,
)

router = APIRouter(
    prefix="/financial-rules",
    tags=["financial-rules"],
)


@router.post(
    "",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_financial_rule(
    rule_data: FinancialRuleCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.create_rule(
        db_session=db_session, rule_data=rule_data, user_id=current_user.id,
    )


@router.get(
    "",
    response_model=list[FinancialRuleResponse],
    status_code=status.HTTP_200_OK,
)
def get_financial_rules(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.get_rules(db_session=db_session, user_id=current_user.id)


@router.get(
    "/{rule_id}",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_200_OK,
)
def get_financial_rule(
    rule_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.get_rule(
        db_session=db_session, rule_id=rule_id, user_id=current_user.id,
    )


@router.patch(
    "/{rule_id}",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_200_OK,
)
def update_financial_rule(
    rule_id: UUID,
    update_data: FinancialRuleUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.update_rule(
        db_session=db_session, rule_id=rule_id, update_data=update_data, user_id=current_user.id,
    )


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_rule(
    rule_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    financial_rule_service.delete_rule(
        db_session=db_session, rule_id=rule_id, user_id=current_user.id,
    )


@router.post(
    "/{rule_id}/enable",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_200_OK,
)
def enable_financial_rule(
    rule_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.enable_rule(
        db_session=db_session, rule_id=rule_id, user_id=current_user.id,
    )


@router.post(
    "/{rule_id}/pause",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_200_OK,
)
def pause_financial_rule(
    rule_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.pause_rule(
        db_session=db_session, rule_id=rule_id, user_id=current_user.id,
    )


@router.post(
    "/{rule_id}/disable",
    response_model=FinancialRuleResponse,
    status_code=status.HTTP_200_OK,
)
def disable_financial_rule(
    rule_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    return financial_rule_service.disable_rule(
        db_session=db_session, rule_id=rule_id, user_id=current_user.id,
    )
