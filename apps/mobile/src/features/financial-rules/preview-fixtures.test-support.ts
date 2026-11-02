// Fixtures shared by the VF-020F5 tests (not a test file itself).
import { ApiError } from "../../api/api-error.ts";
import type { FinancialRule, RulePreview } from "./financial-rule.types.ts";

export const USER_A = "user-a";
export const USER_B = "user-b";
const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const GOAL_1 = "22222222-2222-4222-8222-222222222222";
const GOAL_2 = "33333333-3333-4333-8333-333333333333";

export const GOALS = { first: GOAL_1, second: GOAL_2 };

export const allocationRule = (
  over: Partial<Extract<FinancialRule, { rule_type: "INCOME_ALLOCATION" }>> = {},
): Extract<FinancialRule, { rule_type: "INCOME_ALLOCATION" }> => ({
  id: "rule-1", user_id: USER_A, version: 3, active_since: null, created_at: "t", updated_at: "t", description: null,
  name: "Save", status: "draft", rule_type: "INCOME_ALLOCATION", source_account_id: ACCOUNT,
  execution_mode: "AUTO", execution_order: 1, effective_from: null, policy: "FIXED_PER_GOAL", percent: null,
  cap_at_target: true, allow_partial: false, income_sources: ["salary"], targets: [],
  ...over,
});

export const floorRule = (): FinancialRule => ({
  id: "rule-f", user_id: USER_A, version: 1, active_since: null, created_at: "t", updated_at: "t", description: null,
  name: "Floor", status: "draft", rule_type: "MINIMUM_UNALLOCATED_FLOOR", source_account_id: ACCOUNT, floor_amount: "10.00",
});

export const preview = (over: Partial<RulePreview> = {}): RulePreview => ({
  hypothetical: true,
  rule_id: "rule-1",
  rule_version: 3,
  rule_status: "draft",
  execution_mode: "AUTO",
  policy: "FIXED_PER_GOAL",
  as_of_date: "2026-11-02",
  computed_at: "2026-11-02T09:30:00.123456+00:00",
  sample_income: { amount: "3000.00", currency: "EUR", source: "salary", source_selected_by_rule: true },
  capacity: {
    account_id: ACCOUNT, currency: "EUR", actual_reservable: "1200.00", assumed_income_credit: "3000.00",
    hypothetical_reservable: "4200.00", minimum_unallocated_floor: "500.00", active_rule_holds: "100.00",
    rule_capacity: "3600.00",
  },
  predicted_outcome: "partial",
  effect: "would_apply",
  reason_code: null,
  items: [
    { goal_id: GOAL_1, position: 0, priority_rank: 1, planned_amount: "300.00", selected_amount: "300.00" },
    { goal_id: GOAL_2, position: 1, priority_rank: 2, planned_amount: "150.00", selected_amount: "0.00" },
  ],
  planned_total: "450.00",
  selected_total: "300.00",
  notices: ["hypothetical_snapshot", "income_not_recorded", "real_event_eligibility_not_simulated", "other_enabled_rules_not_simulated", "rule_not_enabled"],
  ...over,
});

export const apiError = (kind: "timeout" | "network" | "malformed_response" | "http", status?: number, code?: string): ApiError =>
  new ApiError({ kind, message: "x", status: status ?? null, code: code ?? null });
