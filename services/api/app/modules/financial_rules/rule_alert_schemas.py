from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RuleAlertResponse(BaseModel):
    """
    One informational alert (§17, §19.3a).

    What:
        A Budget level transition (watch / at_risk / exceeded for a period start)
        or an Account floor-breach / overcommitment episode (level `breached`,
        period_key E1, E2, ...).

    Why:
        An alert never blocks anything and never moves money. subject_name is
        the current name of the Account or Budget, or null once it was deleted;
        rule_id is null once the originating rule was deleted. resolved_at is
        set when an Account episode ended (the Account recovered).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: Optional[UUID]
    rule_type: Literal["MINIMUM_UNALLOCATED_FLOOR", "OVERCOMMITMENT_ALERT", "BUDGET_ALERT"]
    subject_type: Literal["account", "budget"]
    subject_id: UUID
    subject_name: Optional[str] = None
    period_key: str
    level: Literal["watch", "at_risk", "exceeded", "breached"]
    created_at: datetime
    acknowledged_at: Optional[datetime]
    resolved_at: Optional[datetime]


class RuleAlertListResponse(BaseModel):
    items: list[RuleAlertResponse]
    total: int
    limit: int
    offset: int
    available: bool = Field(
        default=True,
        description="False while the rule_alerts schema is not available in this database.",
    )
