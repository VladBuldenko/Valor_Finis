// Fixtures shared by the VF-020F6 tests (not a test file itself).
import type {
  ExecutionStatus,
  RuleExecution,
  RuleExecutionAudit,
  RuleExecutionItem,
  RuleExecutionList,
} from "./financial-rule.types.ts";

export const RULE_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const RULE_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const GOAL_1 = "22222222-2222-4222-8222-222222222222";
export const GOAL_2 = "33333333-3333-4333-8333-333333333333";

export const item = (over: Partial<RuleExecutionItem> = {}): RuleExecutionItem => ({
  id: "item-1",
  goal_id: GOAL_1,
  account_id: "acc-1",
  position: 0,
  planned_amount: "300.00",
  applied_amount: "300.00",
  goal_transaction_id: "tx-1",
  ...over,
});

export const audit = (over: Partial<RuleExecutionAudit> = {}): RuleExecutionAudit => ({
  id: "audit-1",
  code: "applied",
  actor: "system",
  related_event_id: null,
  details: null,
  created_at: "2026-11-02T09:00:00+00:00",
  ...over,
});

export const execution = (over: Partial<RuleExecution> = {}): RuleExecution => ({
  id: "exec-1",
  rule_id: RULE_1,
  rule_version: 3,
  status: "executed",
  reason_code: null,
  source_type: "income",
  source_id: "income-1",
  triggering_event_id: "event-1",
  source_amount: "3000.00",
  source_currency: "EUR",
  source_received_at: "2026-11-02",
  source_account_id: "acc-1",
  source_income_source: "salary",
  capacity_reservable: "1200.00",
  capacity_floor: "500.00",
  capacity_holds: "100.00",
  decided_at: "2026-11-02T09:00:01+00:00",
  created_at: "2026-11-02T09:00:00+00:00",
  items: [item()],
  audit: [audit()],
  ...over,
});

export const page = (
  ids: string[],
  total: number,
  offset: number,
  make: (id: string) => Partial<RuleExecution> = () => ({}),
): RuleExecutionList => ({
  items: ids.map((id) => execution({ id, ...make(id) })),
  total,
  limit: 20,
  offset,
});

export const ids = (count: number, from = 0, prefix = "e"): string[] =>
  Array.from({ length: count }, (_, i) => `${prefix}${from + i}`);

// Reason codes the backend persists on an execution (planner + cancellation).
export const PERSISTED_REASON_CODES = [
  "insufficient_capacity",
  "nothing_to_allocate",
  "source_account_archived",
  "target_goal_archived",
  "currency_mismatch",
  "superseded",
  "stale",
  "source_changed",
  "source_deleted",
  "rule_inactive",
] as const;

export const STATUS_REASONS: Record<ExecutionStatus, string | null> = {
  awaiting_confirmation: null,
  executed: null,
  executed_partial: null,
  skipped: "nothing_to_allocate",
  blocked: "source_account_archived",
  rejected: null,
  expired: null,
  cancelled: "superseded",
};
