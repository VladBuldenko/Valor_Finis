// Pure request construction for the Smart Rules API (VF-020F1): paths, query
// strings and JSON bodies. No I/O, so the exact wire shape is unit-testable.
//
// Invalid ids, pagination bounds and sample amounts are rejected here with a
// RangeError instead of being sent: the backend stays authoritative, but a
// malformed value must never be spliced into a URL path.
import type {
  FinancialRuleCreate,
  FinancialRuleUpdate,
  IncomeSource,
  PaginationParams,
  RuleAction,
  RuleAlertFilters,
  RuleExecutionFilters,
  RulePreviewRequest,
  RuleProposalFilters,
} from "./financial-rule.types.ts";

const API_PREFIX = "/api/v1";

export const FINANCIAL_RULES_PATH = `${API_PREFIX}/financial-rules`;
export const RULE_PROPOSALS_PATH = `${API_PREFIX}/rule-proposals`;
export const RULE_ALERTS_PATH = `${API_PREFIX}/rule-alerts`;
export const RULE_EXECUTIONS_PATH = `${API_PREFIX}/rule-executions`;

// Backend bounds (Query(ge=1, le=100) / ge=0) for every paginated list.
export const MIN_PAGE_LIMIT = 1;
export const MAX_PAGE_LIMIT = 100;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Same shape as the backend's Income amount: positive, up to 12 digits, 2 decimals.
const SAMPLE_AMOUNT_PATTERN = /^\d{1,10}(\.\d{1,2})?$/;

export type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

export type RequestSpec = {
  method: HttpMethod;
  path: string;
  // Already serialised; absent for body-less requests.
  body?: string;
};

export function assertUuid(value: string, label: string): string {
  if (!UUID_PATTERN.test(value)) {
    throw new RangeError(`${label} must be a UUID.`);
  }

  return value;
}

function isPositiveDecimal(value: string): boolean {
  return SAMPLE_AMOUNT_PATTERN.test(value) && /[1-9]/.test(value);
}

function pageParams(page: PaginationParams): string[] {
  const parts: string[] = [];

  if (page.limit !== undefined) {
    if (!Number.isInteger(page.limit) || page.limit < MIN_PAGE_LIMIT || page.limit > MAX_PAGE_LIMIT) {
      throw new RangeError(`limit must be an integer from ${MIN_PAGE_LIMIT} to ${MAX_PAGE_LIMIT}.`);
    }

    parts.push(`limit=${page.limit}`);
  }

  if (page.offset !== undefined) {
    if (!Number.isInteger(page.offset) || page.offset < 0) {
      throw new RangeError("offset must be a non-negative integer.");
    }

    parts.push(`offset=${page.offset}`);
  }

  return parts;
}

function withQuery(path: string, parts: string[]): string {
  return parts.length === 0 ? path : `${path}?${parts.join("&")}`;
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

function rulePath(ruleId: string): string {
  return `${FINANCIAL_RULES_PATH}/${assertUuid(ruleId, "ruleId")}`;
}

function proposalPath(proposalId: string): string {
  return `${RULE_PROPOSALS_PATH}/${assertUuid(proposalId, "proposalId")}`;
}

// ---------------------------------------------------------------- rules

export const listRulesRequest = (): RequestSpec => ({
  method: "GET",
  path: FINANCIAL_RULES_PATH,
});

export const getRuleRequest = (ruleId: string): RequestSpec => ({
  method: "GET",
  path: rulePath(ruleId),
});

export const createRuleRequest = (rule: FinancialRuleCreate): RequestSpec => ({
  method: "POST",
  path: FINANCIAL_RULES_PATH,
  body: jsonBody(rule),
});

export const updateRuleRequest = (ruleId: string, update: FinancialRuleUpdate): RequestSpec => ({
  method: "PATCH",
  path: rulePath(ruleId),
  body: jsonBody(update),
});

export const deleteRuleRequest = (ruleId: string): RequestSpec => ({
  method: "DELETE",
  path: rulePath(ruleId),
});

export const ruleActionRequest = (ruleId: string, action: RuleAction): RequestSpec => ({
  method: "POST",
  path: `${rulePath(ruleId)}/${action}`,
});

// ----------------------------------------------------- evaluate / preview

// The server's drain `limit` query parameter is deliberately not exposed: the
// server default bounds every drain, and the client never loops on it.
export const evaluateRulesRequest = (): RequestSpec => ({
  method: "POST",
  path: `${FINANCIAL_RULES_PATH}/evaluate`,
});

export function buildPreviewRequest(amount: string, source?: IncomeSource): RulePreviewRequest {
  if (!isPositiveDecimal(amount)) {
    throw new RangeError("The sample income must be a positive amount with at most 2 decimals.");
  }

  return { sample_income: source === undefined ? { amount } : { amount, source } };
}

export const previewRuleRequest = (ruleId: string, request: RulePreviewRequest): RequestSpec => {
  // Re-validated so a hand-built request cannot bypass the amount shape.
  buildPreviewRequest(request.sample_income.amount, request.sample_income.source);

  return {
    method: "POST",
    path: `${rulePath(ruleId)}/preview`,
    body: jsonBody(request),
  };
};

// ------------------------------------------------------------ proposals

export const listProposalsRequest = (filters: RuleProposalFilters = {}): RequestSpec => {
  const parts = pageParams(filters);

  if (filters.status !== undefined) {
    parts.push(`status=${filters.status}`);
  }

  return { method: "GET", path: withQuery(RULE_PROPOSALS_PATH, parts) };
};

export const getProposalRequest = (proposalId: string): RequestSpec => ({
  method: "GET",
  path: proposalPath(proposalId),
});

export const confirmProposalRequest = (proposalId: string): RequestSpec => ({
  method: "POST",
  path: `${proposalPath(proposalId)}/confirm`,
});

export const rejectProposalRequest = (proposalId: string): RequestSpec => ({
  method: "POST",
  path: `${proposalPath(proposalId)}/reject`,
});

// --------------------------------------------------------------- alerts

export const listAlertsRequest = (filters: RuleAlertFilters = {}): RequestSpec => {
  const parts = pageParams(filters);

  if (filters.acknowledged !== undefined) {
    parts.push(`acknowledged=${filters.acknowledged ? "true" : "false"}`);
  }

  return { method: "GET", path: withQuery(RULE_ALERTS_PATH, parts) };
};

export const acknowledgeAlertRequest = (alertId: string): RequestSpec => ({
  method: "POST",
  path: `${RULE_ALERTS_PATH}/${assertUuid(alertId, "alertId")}/acknowledge`,
});

// ----------------------------------------------------------- executions

export const listExecutionsRequest = (filters: RuleExecutionFilters = {}): RequestSpec => {
  const parts = pageParams(filters);

  if (filters.rule_id !== undefined) {
    parts.push(`rule_id=${assertUuid(filters.rule_id, "rule_id")}`);
  }

  if (filters.status !== undefined) {
    parts.push(`status=${filters.status}`);
  }

  return { method: "GET", path: withQuery(RULE_EXECUTIONS_PATH, parts) };
};
