from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

RULE_TYPE_INCOME_ALLOCATION = "INCOME_ALLOCATION"
RULE_TYPE_FLOOR = "MINIMUM_UNALLOCATED_FLOOR"
RULE_TYPE_OVERCOMMITMENT = "OVERCOMMITMENT_ALERT"
RULE_TYPE_BUDGET_ALERT = "BUDGET_ALERT"

IncomeSource = Literal["salary", "freelance", "refund", "gift", "other"]

# P35: refund is excluded by default.
DEFAULT_INCOME_SOURCES: list[str] = ["salary", "freelance", "gift", "other"]

MAX_TARGETS_PER_RULE = 50


class FinancialRuleGoalTargetInput(BaseModel):
    """
    One Goal targeted by an INCOME_ALLOCATION rule (request).

    What:
        goal_id, the single amount_or_cap and a configuration position.

    Why:
        position is configuration / UI order only - never the financial
        priority, which is always the Goal's current priority_rank.
        amount_or_cap is the fixed amount for FIXED_PER_GOAL and an optional
        per-target cap for the percentage policy; policy-level requirements
        are validated on the rule.
    """

    model_config = ConfigDict(extra="forbid")

    goal_id: UUID

    amount_or_cap: Optional[Decimal] = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Fixed amount (FIXED_PER_GOAL) or optional per-target cap.",
        examples=["300.00"],
    )

    position: Optional[int] = Field(
        default=None,
        ge=0,
        description="Configuration order only. Defaults to the list index.",
    )


class FinancialRuleGoalTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    amount_or_cap: Optional[Decimal]
    position: int


class _RuleCreateBase(BaseModel):
    # extra="forbid": user_id, version, status, active_since and timestamps can
    # never be written by a client.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150, examples=["Save from salary"])

    description: Optional[str] = Field(default=None, max_length=255)


class IncomeAllocationRuleCreate(_RuleCreateBase):
    """Create schema for an INCOME_ALLOCATION rule (always created as draft)."""

    rule_type: Literal["INCOME_ALLOCATION"]

    source_account_id: UUID

    execution_mode: Literal["AUTO", "CONFIRM"]

    execution_order: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Evaluation order. Omitted: appended after the user's current "
            "maximum. Duplicates and gaps are allowed."
        ),
    )

    effective_from: Optional[date] = None

    policy: Literal["FIXED_PER_GOAL", "PERCENT_OF_INCOME_WATERFALL"]

    percent: Optional[Decimal] = Field(
        default=None, gt=0, le=100, max_digits=5, decimal_places=2,
    )

    cap_at_target: bool = True

    allow_partial: bool = False

    income_sources: list[IncomeSource] = Field(
        default_factory=lambda: list(DEFAULT_INCOME_SOURCES), min_length=1,
    )

    targets: list[FinancialRuleGoalTargetInput] = Field(
        min_length=1, max_length=MAX_TARGETS_PER_RULE,
    )

    @model_validator(mode="after")
    def _validate_policy_shape(self) -> "IncomeAllocationRuleCreate":
        if len(set(self.income_sources)) != len(self.income_sources):
            raise ValueError("income_sources must not contain duplicates.")

        goal_ids = [target.goal_id for target in self.targets]

        if len(set(goal_ids)) != len(goal_ids):
            raise ValueError("A Goal can be targeted only once per rule.")

        if self.policy == "FIXED_PER_GOAL":
            if self.percent is not None:
                raise ValueError("percent is only valid for PERCENT_OF_INCOME_WATERFALL.")

            if any(target.amount_or_cap is None for target in self.targets):
                raise ValueError("FIXED_PER_GOAL requires a positive amount_or_cap on every target.")
        elif self.percent is None:
            raise ValueError("PERCENT_OF_INCOME_WATERFALL requires percent.")

        return self


class FloorRuleCreate(_RuleCreateBase):
    """Create schema for a MINIMUM_UNALLOCATED_FLOOR rule."""

    rule_type: Literal["MINIMUM_UNALLOCATED_FLOOR"]

    source_account_id: UUID

    floor_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2, examples=["1000.00"])


class OvercommitmentAlertRuleCreate(_RuleCreateBase):
    """Create schema for an OVERCOMMITMENT_ALERT rule (draft-only in E5)."""

    rule_type: Literal["OVERCOMMITMENT_ALERT"]

    source_account_id: UUID


class BudgetAlertRuleCreate(_RuleCreateBase):
    """Create schema for a BUDGET_ALERT rule (draft-only in E5)."""

    rule_type: Literal["BUDGET_ALERT"]

    budget_id: UUID


FinancialRuleCreate = Annotated[
    Union[
        IncomeAllocationRuleCreate,
        FloorRuleCreate,
        OvercommitmentAlertRuleCreate,
        BudgetAlertRuleCreate,
    ],
    Field(discriminator="rule_type"),
]

# Used by the service to re-validate the merged state of a PATCH against the
# same rules as a create.
financial_rule_create_adapter: TypeAdapter = TypeAdapter(FinancialRuleCreate)


class FinancialRuleUpdate(BaseModel):
    """
    PATCH schema: every field optional; the service accepts only the fields
    that are valid for the stored rule's type.

    Why:
        status, version, active_since, user_id and timestamps are not
        accepted (status changes use the enable / pause / disable actions).
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=255)
    source_account_id: Optional[UUID] = None
    budget_id: Optional[UUID] = None
    execution_mode: Optional[Literal["AUTO", "CONFIRM"]] = None
    execution_order: Optional[int] = Field(default=None, ge=1)
    effective_from: Optional[date] = None
    policy: Optional[Literal["FIXED_PER_GOAL", "PERCENT_OF_INCOME_WATERFALL"]] = None
    percent: Optional[Decimal] = Field(
        default=None, gt=0, le=100, max_digits=5, decimal_places=2,
    )
    cap_at_target: Optional[bool] = None
    allow_partial: Optional[bool] = None
    income_sources: Optional[list[IncomeSource]] = Field(default=None, min_length=1)
    targets: Optional[list[FinancialRuleGoalTargetInput]] = Field(
        default=None, min_length=1, max_length=MAX_TARGETS_PER_RULE,
    )
    floor_amount: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2,
    )


class _RuleResponseBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: Optional[str]
    status: Literal["draft", "enabled", "paused", "disabled"]
    version: int
    active_since: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class IncomeAllocationRuleResponse(_RuleResponseBase):
    rule_type: Literal["INCOME_ALLOCATION"]
    source_account_id: UUID
    execution_mode: Literal["AUTO", "CONFIRM"]
    execution_order: int
    effective_from: Optional[date]
    policy: Literal["FIXED_PER_GOAL", "PERCENT_OF_INCOME_WATERFALL"]
    percent: Optional[Decimal]
    cap_at_target: bool
    allow_partial: bool
    income_sources: list[IncomeSource]
    targets: list[FinancialRuleGoalTargetResponse]


class FloorRuleResponse(_RuleResponseBase):
    rule_type: Literal["MINIMUM_UNALLOCATED_FLOOR"]
    source_account_id: UUID
    floor_amount: Decimal


class OvercommitmentAlertRuleResponse(_RuleResponseBase):
    rule_type: Literal["OVERCOMMITMENT_ALERT"]
    source_account_id: UUID


class BudgetAlertRuleResponse(_RuleResponseBase):
    rule_type: Literal["BUDGET_ALERT"]
    budget_id: UUID


FinancialRuleResponse = Annotated[
    Union[
        IncomeAllocationRuleResponse,
        FloorRuleResponse,
        OvercommitmentAlertRuleResponse,
        BudgetAlertRuleResponse,
    ],
    Field(discriminator="rule_type"),
]
