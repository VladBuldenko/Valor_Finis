from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.financial_events import financial_event_processor
from app.modules.financial_rules import (
    financial_rule_service,
    rule_alert_service,
    rule_preview_service,
)
from app.modules.financial_rules.financial_rule_schemas import (
    FinancialRuleCreate,
    FinancialRuleResponse,
    FinancialRuleUpdate,
)
from app.modules.financial_rules.rule_execution_schemas import RuleEvaluationResponse
from app.modules.financial_rules.rule_preview_schemas import (
    RulePreviewRequest,
    RulePreviewResponse,
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


# Drains ONLY the caller's own due income events (bounded, strict FIFO) and
# runs their AUTO rules (VF-020E7). Idempotent; it creates no new identities
# and never scans historical Income. It is a user-triggered durable drain, not
# an unattended scheduler (that is VF-020E10).
@router.post(
    "/evaluate",
    response_model=RuleEvaluationResponse,
    status_code=status.HTTP_200_OK,
)
def evaluate_financial_rules(
    limit: int = Query(
        default=financial_event_processor.DEFAULT_DRAIN_LIMIT,
        ge=1,
        le=financial_event_processor.MAX_DRAIN_LIMIT,
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    summary = financial_event_processor.drain_user_events(
        db_session=db_session, user_id=current_user.id, limit=limit,
    )

    # Alerts are detected at evaluation (§17): after the drain, and never able to
    # hide its result.
    alerts = rule_alert_service.evaluate_user_alerts_best_effort(db_session, current_user.id)

    return RuleEvaluationResponse(
        alerts_available=alerts.available,
        alerts_created=alerts.created,
        alerts_resolved=alerts.resolved,
        alerts_failed=alerts.failed,
        processed=summary.processed,
        deferred=summary.deferred,
        failed_retryable=summary.failed_retryable,
        dead=summary.dead,
        blocked=summary.blocked,
        outcomes=summary.outcomes,
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


# Hypothetical, read-only dry run of an allocation rule for a sample income. It
# opens its own READ ONLY transaction (rule_preview_service), so it takes no
# database session from the request and can never write.
@router.post(
    "/{rule_id}/preview",
    response_model=RulePreviewResponse,
    status_code=status.HTTP_200_OK,
)
def preview_financial_rule(
    rule_id: UUID,
    preview_request: RulePreviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return rule_preview_service.preview_rule(
        user_id=current_user.id, rule_id=rule_id, request=preview_request,
    )
