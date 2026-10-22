from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RuleEvaluationResponse(BaseModel):
    """
    Result of one bounded drain of the caller's own due income events.

    What:
        Counters only: events processed, deferred and failed, whether the
        user's queue is blocked by a leased or waiting head, and the committed
        execution outcomes by status.

    Why:
        Evaluation is idempotent and creates no new identities: it only drains
        the durable outbox. Delivery is at least once; the financial effect is
        exactly once through the execution key.
    """

    processed: int
    deferred: int
    failed_retryable: int
    dead: int
    blocked: bool
    outcomes: dict[str, int] = Field(default_factory=dict)


class RuleExecutionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    account_id: UUID
    position: int
    planned_amount: Decimal
    applied_amount: Optional[Decimal]
    goal_transaction_id: Optional[UUID]


class RuleExecutionAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    actor: str
    related_event_id: Optional[UUID]
    details: Optional[dict[str, Any]]
    created_at: datetime


class RuleExecutionResponse(BaseModel):
    """
    Backend read model of one rule execution with its items and audit trail
    (§20.4). Amounts are Decimal strings; the capacity fields are the
    snapshot taken when the rule ran.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    rule_version: int
    status: Literal[
        "awaiting_confirmation", "executed", "executed_partial", "skipped",
        "blocked", "rejected", "expired", "cancelled",
    ]
    reason_code: Optional[str]
    source_type: str
    source_id: UUID
    triggering_event_id: UUID
    source_amount: Decimal
    source_currency: str
    source_received_at: date
    source_account_id: Optional[UUID]
    source_income_source: str
    capacity_reservable: Optional[Decimal]
    capacity_floor: Optional[Decimal]
    capacity_holds: Optional[Decimal]
    decided_at: Optional[datetime]
    created_at: datetime
    items: list[RuleExecutionItemResponse]
    audit: list[RuleExecutionAuditResponse]


class RuleExecutionListResponse(BaseModel):
    items: list[RuleExecutionResponse]
    total: int
    limit: int
    offset: int
