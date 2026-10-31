from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.financial_rules.financial_rule_schemas import IncomeSource


class SampleIncome(BaseModel):
    """
    The hypothetical income a preview is computed for (request).

    What:
        A positive Decimal amount and an optional source. The currency is never
        an input: it is the rule's source Account currency.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        examples=["3000.00"],
    )

    source: Optional[IncomeSource] = None


class RulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_income: SampleIncome


class SampleIncomeResponse(BaseModel):
    amount: Decimal
    currency: str
    source: Optional[str]
    # None when no source was supplied. Informational only: eligibility is not
    # evaluated by a preview.
    source_selected_by_rule: Optional[bool]


class RulePreviewCapacity(BaseModel):
    account_id: UUID
    currency: str
    # The Account's ACTUAL reservable amount today. The sample income is not in it.
    actual_reservable: Decimal
    # The hypothetical credit assumed for planning: the sample amount, a NEW credit
    # that is not a recorded transaction. The income is NOT recorded.
    assumed_income_credit: Decimal
    # actual_reservable + assumed_income_credit (the sample counted exactly once).
    hypothetical_reservable: Decimal
    minimum_unallocated_floor: Decimal
    active_rule_holds: Decimal
    # hypothetical_reservable - minimum_unallocated_floor - active_rule_holds
    rule_capacity: Decimal


class RulePreviewItem(BaseModel):
    goal_id: UUID
    position: int
    priority_rank: Optional[int]
    planned_amount: Decimal
    selected_amount: Decimal


class RulePreviewResponse(BaseModel):
    """
    A hypothetical, read-only snapshot of what a rule would do for a sample
    income. Nothing was recorded, credited, reserved or held, and it is not a
    promise that a real future income will be eligible.
    """

    hypothetical: Literal[True] = True
    rule_id: UUID
    rule_version: int
    rule_status: str
    execution_mode: Literal["AUTO", "CONFIRM"]
    policy: str
    as_of_date: date
    computed_at: datetime
    sample_income: SampleIncomeResponse
    capacity: RulePreviewCapacity
    predicted_outcome: Literal["full", "partial", "skipped", "blocked"]
    # would_apply: a hypothetical INTERNAL Goal reservation (AUTO); never a bank
    #   transfer. would_hold: a hypothetical 168-hour CONFIRM proposal and hold;
    #   nothing is reserved until the user confirms. Preview itself creates
    #   neither. none: skipped or blocked.
    effect: Literal["would_apply", "would_hold", "none"]
    reason_code: Optional[str]
    items: list[RulePreviewItem]
    planned_total: Decimal
    selected_total: Decimal
    notices: list[str]
