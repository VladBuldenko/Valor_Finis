// Wire types of the Smart Rules API (VF-020F1). They mirror the FastAPI
// schemas in services/api/app/modules/financial_rules/*_schemas.py field for
// field; nothing here is invented. Where the backend declares a plain `str`
// (reason codes, preview notices, audit codes) the type stays `string` and a
// mapper (financial-rule-presentation.ts) owns the known values and the
// fallback.
//
// Money: every amount, percent and floor is a DECIMAL STRING ("300.00") on
// both the request and the response side. It is never parsed into a number
// here and never computed on the client.

export type DecimalString = string;
// ISO calendar date, "YYYY-MM-DD".
export type IsoDate = string;
// ISO-8601 timestamp with offset.
export type IsoDateTime = string;

export const RULE_TYPES = [
  "INCOME_ALLOCATION",
  "MINIMUM_UNALLOCATED_FLOOR",
  "OVERCOMMITMENT_ALERT",
  "BUDGET_ALERT",
] as const;
export type RuleType = (typeof RULE_TYPES)[number];

export const EXECUTION_MODES = ["AUTO", "CONFIRM"] as const;
export type ExecutionMode = (typeof EXECUTION_MODES)[number];

export const RULE_POLICIES = ["FIXED_PER_GOAL", "PERCENT_OF_INCOME_WATERFALL"] as const;
export type RulePolicy = (typeof RULE_POLICIES)[number];

export const RULE_STATUSES = ["draft", "enabled", "paused", "disabled"] as const;
export type RuleStatus = (typeof RULE_STATUSES)[number];

export const INCOME_SOURCES = ["salary", "freelance", "refund", "gift", "other"] as const;
export type IncomeSource = (typeof INCOME_SOURCES)[number];

// Backend default (P35): refund is not selected unless the user adds it.
export const DEFAULT_INCOME_SOURCES: readonly IncomeSource[] = [
  "salary",
  "freelance",
  "gift",
  "other",
];

export const MAX_TARGETS_PER_RULE = 50;

// ---------------------------------------------------------------- rules

export type RuleGoalTarget = {
  id: string;
  goal_id: string;
  // Fixed amount (FIXED_PER_GOAL) or optional per-target cap (percent policy).
  amount_or_cap: DecimalString | null;
  // Configuration order only; the financial priority is the Goal's priority_rank.
  position: number;
};

type RuleBase = {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  status: RuleStatus;
  version: number;
  active_since: IsoDateTime | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
};

export type IncomeAllocationRule = RuleBase & {
  rule_type: "INCOME_ALLOCATION";
  source_account_id: string;
  execution_mode: ExecutionMode;
  execution_order: number;
  effective_from: IsoDate | null;
  policy: RulePolicy;
  percent: DecimalString | null;
  cap_at_target: boolean;
  allow_partial: boolean;
  income_sources: IncomeSource[];
  targets: RuleGoalTarget[];
};

export type FloorRule = RuleBase & {
  rule_type: "MINIMUM_UNALLOCATED_FLOOR";
  source_account_id: string;
  floor_amount: DecimalString;
};

export type OvercommitmentAlertRule = RuleBase & {
  rule_type: "OVERCOMMITMENT_ALERT";
  source_account_id: string;
};

export type BudgetAlertRule = RuleBase & {
  rule_type: "BUDGET_ALERT";
  budget_id: string;
};

export type FinancialRule =
  | IncomeAllocationRule
  | FloorRule
  | OvercommitmentAlertRule
  | BudgetAlertRule;

export type RuleGoalTargetInput = {
  goal_id: string;
  amount_or_cap?: DecimalString;
  position?: number;
};

type RuleCreateBase = { name: string; description?: string };

// Rules are always created as drafts; status, version, user_id and
// timestamps are never sent (the backend forbids extra fields).
export type IncomeAllocationRuleCreate = RuleCreateBase & {
  rule_type: "INCOME_ALLOCATION";
  source_account_id: string;
  execution_mode: ExecutionMode;
  execution_order?: number;
  effective_from?: IsoDate;
  policy: RulePolicy;
  percent?: DecimalString;
  cap_at_target?: boolean;
  allow_partial?: boolean;
  income_sources?: IncomeSource[];
  targets: RuleGoalTargetInput[];
};

export type FloorRuleCreate = RuleCreateBase & {
  rule_type: "MINIMUM_UNALLOCATED_FLOOR";
  source_account_id: string;
  floor_amount: DecimalString;
};

export type OvercommitmentAlertRuleCreate = RuleCreateBase & {
  rule_type: "OVERCOMMITMENT_ALERT";
  source_account_id: string;
};

export type BudgetAlertRuleCreate = RuleCreateBase & {
  rule_type: "BUDGET_ALERT";
  budget_id: string;
};

export type FinancialRuleCreate =
  | IncomeAllocationRuleCreate
  | FloorRuleCreate
  | OvercommitmentAlertRuleCreate
  | BudgetAlertRuleCreate;

// PATCH body: only the fields that changed. The backend accepts the subset
// valid for the stored rule's type and rejects the rest with 422.
//
// The backend accepts an explicit null for exactly three fields, to CLEAR
// them (NULLABLE_UPDATE_FIELDS): description, effective_from and percent.
// Any other explicit null is a 422.
export type FinancialRuleUpdate = {
  name?: string;
  description?: string | null;
  source_account_id?: string;
  budget_id?: string;
  execution_mode?: ExecutionMode;
  execution_order?: number;
  effective_from?: IsoDate | null;
  policy?: RulePolicy;
  percent?: DecimalString | null;
  cap_at_target?: boolean;
  allow_partial?: boolean;
  income_sources?: IncomeSource[];
  targets?: RuleGoalTargetInput[];
  floor_amount?: DecimalString;
};

// The three status actions the API offers (POST /financial-rules/{id}/<action>).
export const RULE_ACTIONS = ["enable", "pause", "disable"] as const;
export type RuleAction = (typeof RULE_ACTIONS)[number];

// ----------------------------------------------------------- evaluation

export type RuleEvaluationResult = {
  processed: number;
  deferred: number;
  failed_retryable: number;
  dead: number;
  // True when the user's event queue is blocked by a leased or waiting head.
  blocked: boolean;
  // Committed execution outcomes by status (e.g. {"executed": 1}).
  outcomes: Record<string, number>;
  alerts_available: boolean;
  alerts_created: number;
  alerts_resolved: number;
  // True when alert evaluation raised; the drain counters are still valid.
  alerts_failed: boolean;
};

// ------------------------------------------------------ pagination

export type PaginationParams = { limit?: number; offset?: number };

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

// ----------------------------------------------------------- proposals

export const PROPOSAL_STATUSES = [
  "awaiting_confirmation",
  "executed",
  "executed_partial",
  "rejected",
  "expired",
  "cancelled",
] as const;
export type ProposalStatus = (typeof PROPOSAL_STATUSES)[number];

export type RuleProposalItem = {
  id: string;
  goal_id: string;
  goal_name: string;
  position: number;
  planned_amount: DecimalString;
  applied_amount: DecimalString | null;
  goal_transaction_id: string | null;
  target_amount: DecimalString;
  // The Goal's current total across all partitions.
  current_amount: DecimalString;
  // current_amount + planned_amount while awaiting confirmation.
  expected_amount: DecimalString;
};

export type RuleProposal = {
  id: string;
  rule_id: string;
  rule_name: string;
  rule_version: number;
  status: ProposalStatus;
  reason_code: string | null;
  partial: boolean;
  hold_sequence: number;
  expires_at: IsoDateTime;
  created_at: IsoDateTime;
  decided_at: IsoDateTime | null;
  source_id: string;
  source_amount: DecimalString;
  source_currency: string;
  source_received_at: IsoDate;
  account_id: string | null;
  currency: string;
  planned_total: DecimalString;
  // Present only while awaiting confirmation.
  confirm_capacity: DecimalString | null;
  items: RuleProposalItem[];
};

export type RuleProposalList = PaginatedResponse<RuleProposal>;

export type RuleProposalFilters = PaginationParams & { status?: ProposalStatus };

// -------------------------------------------------------------- alerts

export const ALERT_LEVELS = ["watch", "at_risk", "exceeded", "breached"] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

export const ALERT_RULE_TYPES = [
  "MINIMUM_UNALLOCATED_FLOOR",
  "OVERCOMMITMENT_ALERT",
  "BUDGET_ALERT",
] as const;
export type AlertRuleType = (typeof ALERT_RULE_TYPES)[number];

export type RuleAlert = {
  id: string;
  // Null once the originating rule was deleted.
  rule_id: string | null;
  rule_type: AlertRuleType;
  subject_type: "account" | "budget";
  subject_id: string;
  // Current name of the Account or Budget; null once it was deleted.
  subject_name: string | null;
  period_key: string;
  level: AlertLevel;
  created_at: IsoDateTime;
  acknowledged_at: IsoDateTime | null;
  // Set when an Account episode ended (the Account recovered).
  resolved_at: IsoDateTime | null;
};

// `available: false` means the rule_alerts schema does not exist in this
// environment yet. It is NOT "no alerts" and must never be shown as a clear state.
export type RuleAlertList = PaginatedResponse<RuleAlert> & { available: boolean };

export type RuleAlertFilters = PaginationParams & { acknowledged?: boolean };

// ---------------------------------------------------------- executions

export const EXECUTION_STATUSES = [
  "awaiting_confirmation",
  "executed",
  "executed_partial",
  "skipped",
  "blocked",
  "rejected",
  "expired",
  "cancelled",
] as const;
export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number];

export type RuleExecutionItem = {
  id: string;
  goal_id: string;
  account_id: string;
  position: number;
  planned_amount: DecimalString;
  applied_amount: DecimalString | null;
  goal_transaction_id: string | null;
};

export type RuleExecutionAudit = {
  id: string;
  code: string;
  actor: string;
  related_event_id: string | null;
  // Free-form server diagnostics. Never rendered as-is.
  details: Readonly<Record<string, unknown>> | null;
  created_at: IsoDateTime;
};

export type RuleExecution = {
  id: string;
  rule_id: string;
  rule_version: number;
  status: ExecutionStatus;
  reason_code: string | null;
  source_type: string;
  source_id: string;
  triggering_event_id: string;
  source_amount: DecimalString;
  source_currency: string;
  source_received_at: IsoDate;
  source_account_id: string | null;
  source_income_source: string;
  capacity_reservable: DecimalString | null;
  capacity_floor: DecimalString | null;
  capacity_holds: DecimalString | null;
  decided_at: IsoDateTime | null;
  created_at: IsoDateTime;
  items: RuleExecutionItem[];
  audit: RuleExecutionAudit[];
};

export type RuleExecutionList = PaginatedResponse<RuleExecution>;

export type RuleExecutionFilters = PaginationParams & {
  rule_id?: string;
  status?: ExecutionStatus;
};

// ------------------------------------------------------------- preview

export type SampleIncomeInput = {
  amount: DecimalString;
  source?: IncomeSource;
};

export type RulePreviewRequest = { sample_income: SampleIncomeInput };

export const PREVIEW_OUTCOMES = ["full", "partial", "skipped", "blocked"] as const;
export type PreviewOutcome = (typeof PREVIEW_OUTCOMES)[number];

export const PREVIEW_EFFECTS = ["would_apply", "would_hold", "none"] as const;
export type PreviewEffect = (typeof PREVIEW_EFFECTS)[number];

export type RulePreviewCapacity = {
  account_id: string;
  currency: string;
  // The Account's actual reservable amount today (the sample is not in it).
  actual_reservable: DecimalString;
  // The hypothetical credit assumed for planning (the sample amount).
  assumed_income_credit: DecimalString;
  // actual_reservable + assumed_income_credit.
  hypothetical_reservable: DecimalString;
  minimum_unallocated_floor: DecimalString;
  active_rule_holds: DecimalString;
  // hypothetical_reservable - minimum_unallocated_floor - active_rule_holds.
  rule_capacity: DecimalString;
};

export type RulePreviewItem = {
  goal_id: string;
  position: number;
  priority_rank: number | null;
  planned_amount: DecimalString;
  selected_amount: DecimalString;
};

export type RulePreview = {
  // Always true: nothing was recorded, credited, reserved or held.
  hypothetical: true;
  rule_id: string;
  // A preview is stale once the rule's version changes.
  rule_version: number;
  rule_status: RuleStatus;
  execution_mode: ExecutionMode;
  policy: RulePolicy;
  // Server calendar date the preview used (copy rule C4).
  as_of_date: IsoDate;
  computed_at: IsoDateTime;
  sample_income: {
    amount: DecimalString;
    currency: string;
    source: IncomeSource | null;
    // Null when no source was supplied.
    source_selected_by_rule: boolean | null;
  };
  capacity: RulePreviewCapacity;
  predicted_outcome: PreviewOutcome;
  effect: PreviewEffect;
  reason_code: string | null;
  items: RulePreviewItem[];
  planned_total: DecimalString;
  selected_total: DecimalString;
  notices: string[];
};

// A preview is cached per rule version and exact sample, never per rule id alone.
export type PreviewKeyInput = {
  ruleId: string;
  ruleVersion: number;
  sampleAmount: DecimalString;
  sampleSource: IncomeSource | null;
};

// ---------------------------------------------------------- exhaustiveness

// Makes a `switch` over a union fail to COMPILE when a member is added.
export function assertNever(value: never, context: string): never {
  throw new Error(`Unhandled ${context}: ${String(value)}`);
}
