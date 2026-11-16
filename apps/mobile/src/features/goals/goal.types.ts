export type GoalStatus = "active" | "completed" | "archived";

// Mirrors backend GoalResponse (services/api/app/modules/goals/goal_schemas.py),
// which itself extends GoalBase. Money fields (target_amount, current_amount)
// arrive as JSON strings, matching every other financial contract in this app
// (see Budget in ../budgets/budget.types.ts) -- never parse them for display,
// only render the exact string the backend returns. target_date is nullable:
// a goal can be created without a target date. This slice is read-only, so
// no Create/Update input types are defined here.
//
// VF-020C3 (backend VF-020C2) partitions, all read-only JSON strings:
// - current_amount stays the TOTAL (tracked_amount + linked_amount);
// - tracked_amount is the part not tied to any Account;
// - linked_amount is the part reserved against Accounts;
// - allocations lists the CURRENT non-zero Account partitions (a summary,
//   not a history), ordered by account_id by the backend.
// A reservation earmarks money for the Goal; it never moves money out of an
// Account.
export type GoalAllocation = {
  account_id: string;
  amount: string;
};

export type Goal = {
  id: string;
  user_id: string;
  name: string;
  target_amount: string;
  current_amount: string;
  tracked_amount: string;
  linked_amount: string;
  allocations: GoalAllocation[];
  // VF-020D priority, 1 = highest. Read-only: it changes only through
  // PUT /goals/priorities. null for archived Goals and for non-archived
  // "rollout stragglers" that the backend has not ranked yet (a supported
  // state until VF-020D5), so never assume a non-archived Goal has a rank and
  // never use it as financial data. The backend list order is authoritative.
  priority_rank: number | null;
  currency: string;
  target_date: string | null;
  status: GoalStatus;
  created_at: string;
  updated_at: string;
};

// Mirrors backend GoalCreate (services/api/app/modules/goals/goal_schemas.py).
// user_id is intentionally omitted -- it is derived from authentication on
// the server and must never be sent from the client. current_amount and
// status are intentionally omitted entirely: this UI slice does not expose
// either control, and the backend already defaults them (0 / "active") when
// omitted. currency stays optional and unsent by the create form for the
// same reason Budget's create form never sends it (see BudgetCreateInput /
// budget-create-screen.tsx) -- the app is EUR-first and the backend already
// defaults currency to "EUR". target_date is optional and nullable, matching
// the backend's `date | None` field.
export type GoalCreateInput = {
  name: string;
  target_amount: string;
  currency?: string;
  target_date?: string | null;
};

// Mirrors backend GoalUpdate (services/api/app/modules/goals/goal_schemas.py).
// Every field is optional -- an omitted field is left unchanged by the
// backend (it uses `model_dump(exclude_unset=True)`). target_date is the
// only field where an explicit null is meaningful (it clears the target
// date); the backend rejects an explicit null for name, target_amount,
// currency, and status, so those stay plain optional values rather than
// nullable. currency is part of the backend PATCH contract but
// intentionally unused here -- Edit Goal shows currency read-only and never
// sends it (see goal-edit-screen.tsx). user_id is intentionally omitted --
// it is derived from authentication on the server. current_amount is
// intentionally NOT part of this type (VF-016F): it is no longer
// client-writable at all -- the backend rejects it outright, and funding a
// goal now happens exclusively through a GoalTransaction (see below).
export type GoalUpdateInput = {
  name?: string;
  target_amount?: string;
  currency?: string;
  target_date?: string | null;
  status?: GoalStatus;
};

// Mirrors backend GoalTransactionResponse's `type` field
// (services/api/app/modules/goals/goal_transaction_schemas.py).
// opening_balance is a migration/system-created historical balance entry --
// it can appear in read history but a client can never create one (see
// GoalTransactionCreateInput below).
export type GoalTransactionType =
  | "opening_balance"
  | "contribution"
  | "withdrawal";

// Mirrors backend GoalTransactionResponse. amount is always positive; the
// transaction's `type` carries direction (VF-016B/C), never the amount's
// sign. A GoalTransaction always represents an amount in its parent Goal's
// currency (see Goal.currency above), which is why the backend keeps
// Goal.currency immutable once any GoalTransaction exists (VF-016E). Money
// fields stay JSON strings, matching Goal -- never parse them for display
// or arithmetic, only render the exact string the backend returns.
//
// VF-020B3 runtime fields, all nullable for history recorded before them:
// - currency: copy of the Goal's currency stored with the row (null only
//   for older history -- the Goal's currency still applies).
// - effective_date: business date "YYYY-MM-DD" (null only for older
//   history; display falls back to created_at -- see
//   getGoalTransactionDisplayDate). A date-only string: never parse it
//   into a Date.
// - client_request_id: idempotency key the create request carried, if any.
// VF-020C3 (backend VF-020C2): account_id is the Account a row is reserved
// against (null = tracked row, and every row recorded before reservations
// existed). A non-null account_id makes the row a Reservation (contribution)
// or a Release (withdrawal).
export type GoalTransaction = {
  id: string;
  goal_id: string;
  user_id: string;
  type: GoalTransactionType;
  amount: string;
  description: string | null;
  created_at: string;
  currency: string | null;
  effective_date: string | null;
  client_request_id: string | null;
  account_id: string | null;
};

// Mirrors backend GoalTransactionFloorWarning (VF-020E5/E7): the advisory
// warning on a successful MANUAL LINKED contribution. All amounts are decimal
// strings in the Goal's (= the Account's) currency. The backend alone decides
// whether it is present; the client never predicts it.
export type GoalTransactionFloorWarning = {
  code: "minimum_unallocated_floor";
  minimum_unallocated_floor: string;
  projected_reservable_amount: string;
  projected_rule_capacity: string;
};

// Mirrors backend GoalTransactionCreatedResponse: the unchanged transaction
// plus the additive, non-persisted warnings list. Only the POST response has
// it; the historical GET type (GoalTransaction) is unchanged. `warnings` is
// optional so a response from a server without the field is still valid.
export type GoalTransactionCreated = GoalTransaction & {
  warnings?: GoalTransactionFloorWarning[];
};

// Mirrors backend GoalTransactionCreate. Only contribution and withdrawal
// are reachable here -- the type is deliberately narrower than
// GoalTransaction['type'] above, since opening_balance is
// system/migration-only and the backend rejects it from this endpoint
// (422). user_id/goal_id are intentionally omitted -- user_id comes from
// authentication and goal_id comes from the request path, not the body.
// currency is intentionally absent: the backend always copies it from the
// Goal and rejects a client-sent one.
// client_request_id (VF-020B3) is the create idempotency key: optional in
// the backend contract for older clients, but this app always sends one
// (see goal-transaction-attempts.ts). effective_date is optional too and
// this app never sends it -- the server assigns today's date, which keeps a
// retry after midnight an exact replay -- for tracked and linked requests
// alike.
// account_id (VF-020C3) selects the partition: omitted = tracked, an Account
// id = that Account's linked partition (reservation / release). A linked
// request requires client_request_id, which this app always sends.
export type GoalTransactionCreateInput = {
  type: "contribution" | "withdrawal";
  amount: string;
  description?: string;
  client_request_id?: string;
  effective_date?: string;
  account_id?: string;
};

// VF-GOALS-PLANNING-001: mirrors backend GoalPlanResponse
// (services/api/app/modules/goals/goal_plan_schemas.py), the read-only,
// advisory Goal planning preview from POST /api/v1/goals/{id}/plan. Every
// amount is the backend's decimal string and every date its ISO date: the app
// never calculates, rounds or compares money for the plan, it only shows what
// the backend returned. Nothing here is stored, scheduled or reserved.
export type GoalPlanStatus =
  | "archived"
  | "already_funded"
  | "no_target_date"
  | "target_date_passed"
  | "ready";

export type GoalPlanWhatIfOutcome =
  | "reaches_target"
  | "no_contribution"
  | "not_reachable_within_horizon"
  | "already_funded"
  | "not_applicable";

export type GoalPlanWhatIf = {
  monthly_contribution: string;
  outcome: GoalPlanWhatIfOutcome;
  installments_needed: number | null;
  estimated_completion_date: string | null;
  on_or_before_target_date: boolean | null;
};

export type GoalPlan = {
  goal_id: string;
  currency: string;
  goal_status: GoalStatus;
  as_of: string;
  target_amount: string;
  current_amount: string;
  tracked_amount: string;
  linked_amount: string;
  remaining_amount: string;
  overfunded_amount: string;
  target_date: string | null;
  plan_status: GoalPlanStatus;
  installment_count: number | null;
  required_per_installment: string | null;
  first_installment_date: string | null;
  last_installment_date: string | null;
  horizon_months: number;
  what_if: GoalPlanWhatIf | null;
};

// VF-GOALS-PLANNING-002A: mirrors backend GoalHistoryComparisonResponse
// (services/api/app/modules/goals/goal_history_schemas.py), the read-only,
// advisory comparison of a Goal's required installment with the RECORDED
// income and expenses of the last three completed months, from
// GET /api/v1/goals/{id}/plan/history-comparison. Amounts are the backend's
// decimal strings, never parsed or compared as numbers on the device; the
// status, direction and limitation codes decide every sentence shown.
export type GoalHistoryComparisonStatus =
  | "comparable"
  | "insufficient_data"
  | "currency_mismatch"
  | "no_required_installment";

export type GoalHistoryLimitation =
  | "unresolved_currency_data"
  | "fewer_than_two_active_months"
  | "months_without_activity_excluded"
  | "budgets_not_modelled"
  | "goal_commitments_not_modelled";

export type GoalHistoryDifferenceDirection = "surplus" | "equal" | "shortfall";

export type GoalHistoryMonth = {
  period_start: string;
  period_end: string;
  income_total: string;
  expense_total: string;
  net_flow: string;
  income_count: number;
  expense_count: number;
  unresolved_income_count: number;
  unresolved_expense_count: number;
  has_activity: boolean;
  included_in_average: boolean;
};

export type GoalHistoryComparison = {
  goal_id: string;
  as_of: string;
  goal_currency: string;
  base_currency: string;
  status: GoalHistoryComparisonStatus;
  limitations: GoalHistoryLimitation[];
  analysis_period_start: string;
  analysis_period_end: string;
  months: GoalHistoryMonth[];
  months_used: number;
  average_monthly_income: string | null;
  average_monthly_expenses: string | null;
  average_monthly_net_flow: string | null;
  required_per_installment: string | null;
  historical_difference: string | null;
  difference_direction: GoalHistoryDifferenceDirection | null;
};

// VF-GOALS-PLANNING-002B: mirrors backend GoalSavingsOverviewResponse
// (services/api/app/modules/goals/goal_savings_overview_schemas.py), the
// read-only, advisory sum of every planned Goal's HYPOTHETICAL required
// installment, month by month for 12 calendar months, set next to RECORDED
// history, from GET /api/v1/goals/savings-overview. Amounts are the backend's
// decimal strings, never parsed, added or compared as numbers on the device;
// the status, direction, limitation codes and counts decide every sentence.
export type GoalSavingsComparisonStatus = "comparable" | "insufficient_data" | "no_planned_goals";

export type GoalSavingsLimitation =
  | "unresolved_currency_data"
  | "fewer_than_two_active_months"
  | "months_without_activity_excluded"
  | "other_currency_goals_excluded"
  | "goals_without_target_date"
  | "goals_with_passed_target_date"
  | "budgets_not_modelled"
  | "goal_commitments_not_modelled"
  | "future_obligations_not_modelled";

export type GoalSavingsPlannedGoal = {
  goal_id: string;
  name: string;
  priority_rank: number | null;
  target_date: string;
  remaining_amount: string;
  installment_count: number;
  required_per_installment: string;
  first_installment_date: string;
  last_installment_date: string;
  continues_after_window: boolean;
};

export type GoalSavingsContribution = {
  goal_id: string;
  amount: string;
};

export type GoalSavingsMonth = {
  period_start: string;
  period_end: string;
  installment_date: string;
  total_required: string;
  planned_goal_count: number;
  contributions: GoalSavingsContribution[];
  historical_difference: string | null;
  difference_direction: GoalHistoryDifferenceDirection | null;
};

export type GoalSavingsExclusions = {
  archived: number;
  completed: number;
  already_funded: number;
  no_target_date: number;
  target_date_passed: number;
  other_currency: number;
  other_currencies: string[];
};

export type GoalSavingsHistory = {
  status: GoalSavingsComparisonStatus;
  analysis_period_start: string;
  analysis_period_end: string;
  months: GoalHistoryMonth[];
  months_used: number;
  average_monthly_income: string | null;
  average_monthly_expenses: string | null;
  average_monthly_net_flow: string | null;
};

export type GoalSavingsOverview = {
  as_of: string;
  base_currency: string;
  horizon_months: number;
  is_total_complete: boolean;
  planned_goals: GoalSavingsPlannedGoal[];
  months: GoalSavingsMonth[];
  exclusions: GoalSavingsExclusions;
  history: GoalSavingsHistory;
  limitations: GoalSavingsLimitation[];
};
