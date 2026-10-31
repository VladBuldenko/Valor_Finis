// Centralised TanStack Query keys of the Smart Rules feature (VF-020F1).
//
// Every key is private to one user: family first, then the authenticated
// user's id, then the specifics. That is the convention of the other features
// (["goals", userId], ["accounts", userId]) and it makes a family invalidation
// a plain prefix match. The QueryClient itself is also per user (MF-2), so the
// id is defence in depth, never the only isolation.
//
// userId is required and must be non-empty: a signed-out caller cannot build a
// key, so it cannot read or write a cache entry.
import type {
  ExecutionStatus,
  PreviewKeyInput,
  ProposalStatus,
  RuleAlertFilters,
  RuleExecutionFilters,
  RuleProposalFilters,
} from "./financial-rule.types.ts";

export const RULE_KEY_FAMILIES = {
  rules: "financial-rules",
  proposals: "rule-proposals",
  alerts: "rule-alerts",
  executions: "rule-executions",
  previews: "rule-previews",
} as const;

// Families owned by other features that rule events refresh.
export const EXTERNAL_KEY_FAMILIES = {
  goals: "goals",
  accounts: "accounts",
} as const;

export type QueryKeyTuple = readonly unknown[];

function requireUser(userId: string): string {
  if (typeof userId !== "string" || userId.length === 0) {
    throw new RangeError("A query key needs the authenticated user id.");
  }

  return userId;
}

// Pagination and filters are part of the key as a normalised, fixed-shape
// object so equal requests share one entry and different pages never collide.
function pageKey(filters: { limit?: number; offset?: number }): { limit: number | null; offset: number | null } {
  return { limit: filters.limit ?? null, offset: filters.offset ?? null };
}

export const financialRuleKeys = {
  // Family prefixes (used for invalidation).
  rulesFamily: (userId: string): QueryKeyTuple => [RULE_KEY_FAMILIES.rules, requireUser(userId)],
  proposalsFamily: (userId: string): QueryKeyTuple => [RULE_KEY_FAMILIES.proposals, requireUser(userId)],
  alertsFamily: (userId: string): QueryKeyTuple => [RULE_KEY_FAMILIES.alerts, requireUser(userId)],
  executionsFamily: (userId: string): QueryKeyTuple => [RULE_KEY_FAMILIES.executions, requireUser(userId)],
  previewsFamily: (userId: string): QueryKeyTuple => [RULE_KEY_FAMILIES.previews, requireUser(userId)],

  // Concrete queries.
  ruleList: (userId: string): QueryKeyTuple => [...financialRuleKeys.rulesFamily(userId), "list"],
  ruleDetail: (userId: string, ruleId: string): QueryKeyTuple => [
    ...financialRuleKeys.rulesFamily(userId),
    "detail",
    ruleId,
  ],
  proposalList: (userId: string, filters: RuleProposalFilters = {}): QueryKeyTuple => [
    ...financialRuleKeys.proposalsFamily(userId),
    "list",
    { status: (filters.status ?? null) as ProposalStatus | null, ...pageKey(filters) },
  ],
  proposalDetail: (userId: string, proposalId: string): QueryKeyTuple => [
    ...financialRuleKeys.proposalsFamily(userId),
    "detail",
    proposalId,
  ],
  alertList: (userId: string, filters: RuleAlertFilters = {}): QueryKeyTuple => [
    ...financialRuleKeys.alertsFamily(userId),
    "list",
    { acknowledged: filters.acknowledged ?? null, ...pageKey(filters) },
  ],
  executionList: (userId: string, filters: RuleExecutionFilters = {}): QueryKeyTuple => [
    ...financialRuleKeys.executionsFamily(userId),
    "list",
    {
      rule_id: filters.rule_id ?? null,
      status: (filters.status ?? null) as ExecutionStatus | null,
      ...pageKey(filters),
    },
  ],
  // A preview belongs to one rule VERSION and one exact sample: editing the
  // rule (version + 1) or changing the sample reaches a different entry, so a
  // stale preview can never be shown for a newer rule.
  preview: (userId: string, input: PreviewKeyInput): QueryKeyTuple => [
    ...financialRuleKeys.previewsFamily(userId),
    input.ruleId,
    input.ruleVersion,
    input.sampleAmount,
    input.sampleSource,
  ],
  // All previews of one rule, any version or sample.
  previewsOfRule: (userId: string, ruleId: string): QueryKeyTuple => [
    ...financialRuleKeys.previewsFamily(userId),
    ruleId,
  ],
};

export const goalKeys = {
  family: (userId: string): QueryKeyTuple => [EXTERNAL_KEY_FAMILIES.goals, requireUser(userId)],
  progress: (userId: string): QueryKeyTuple => ["analytics", "goal-progress", requireUser(userId)],
};

export const accountKeys = {
  family: (userId: string): QueryKeyTuple => [EXTERNAL_KEY_FAMILIES.accounts, requireUser(userId)],
};
