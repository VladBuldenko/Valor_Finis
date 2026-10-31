// The 14 Smart Rules endpoints (VF-020F1) over an injected transport. The app
// binds it to apiRequest in financial-rule.service.ts; tests bind it to a fake
// or to the real transport with a fake fetch. This layer never retries and
// never passes a retry option: the transport alone decides (GET only), so a
// POST (create, status action, evaluate, preview, confirm, reject,
// acknowledge) is sent exactly once.
import type { ApiRequestOptions } from "../../api/api-transport.ts";
import {
  acknowledgeAlertRequest,
  confirmProposalRequest,
  createRuleRequest,
  deleteRuleRequest,
  evaluateRulesRequest,
  getProposalRequest,
  getRuleRequest,
  listAlertsRequest,
  listExecutionsRequest,
  listProposalsRequest,
  listRulesRequest,
  previewRuleRequest,
  rejectProposalRequest,
  ruleActionRequest,
  updateRuleRequest,
  type RequestSpec,
} from "./financial-rule-requests.ts";
import type {
  FinancialRule,
  FinancialRuleCreate,
  FinancialRuleUpdate,
  RuleAlert,
  RuleAlertFilters,
  RuleAlertList,
  RuleEvaluationResult,
  RuleExecutionFilters,
  RuleExecutionList,
  RulePreview,
  RulePreviewRequest,
  RuleProposal,
  RuleProposalFilters,
  RuleProposalList,
} from "./financial-rule.types.ts";

export type RequestFn = <T>(path: string, options?: ApiRequestOptions) => Promise<T>;

export type FinancialRulesApi = ReturnType<typeof createFinancialRulesApi>;

export function createFinancialRulesApi(request: RequestFn) {
  function send<T>(spec: RequestSpec, signal?: AbortSignal): Promise<T> {
    const options: ApiRequestOptions = { method: spec.method };

    if (spec.body !== undefined) {
      options.body = spec.body;
    }

    if (signal !== undefined) {
      options.signal = signal;
    }

    return request<T>(spec.path, options);
  }

  return {
    // GET /financial-rules: a plain array (not an envelope).
    listRules: (signal?: AbortSignal) => send<FinancialRule[]>(listRulesRequest(), signal),
    getRule: (ruleId: string, signal?: AbortSignal) =>
      send<FinancialRule>(getRuleRequest(ruleId), signal),
    createRule: (rule: FinancialRuleCreate) => send<FinancialRule>(createRuleRequest(rule)),
    updateRule: (ruleId: string, update: FinancialRuleUpdate) =>
      send<FinancialRule>(updateRuleRequest(ruleId, update)),
    // 204 No Content.
    deleteRule: (ruleId: string) => send<void>(deleteRuleRequest(ruleId)),
    enableRule: (ruleId: string) => send<FinancialRule>(ruleActionRequest(ruleId, "enable")),
    pauseRule: (ruleId: string) => send<FinancialRule>(ruleActionRequest(ruleId, "pause")),
    disableRule: (ruleId: string) => send<FinancialRule>(ruleActionRequest(ruleId, "disable")),

    // POST /financial-rules/evaluate: drains only the caller's own due events.
    evaluateRules: (signal?: AbortSignal) =>
      send<RuleEvaluationResult>(evaluateRulesRequest(), signal),
    // POST .../preview: read-only on the server, but still a POST (never retried).
    previewRule: (ruleId: string, previewRequest: RulePreviewRequest, signal?: AbortSignal) =>
      send<RulePreview>(previewRuleRequest(ruleId, previewRequest), signal),

    listProposals: (filters?: RuleProposalFilters, signal?: AbortSignal) =>
      send<RuleProposalList>(listProposalsRequest(filters), signal),
    getProposal: (proposalId: string, signal?: AbortSignal) =>
      send<RuleProposal>(getProposalRequest(proposalId), signal),
    // The returned `status` decides the outcome, not the HTTP code (rule C5).
    confirmProposal: (proposalId: string) =>
      send<RuleProposal>(confirmProposalRequest(proposalId)),
    rejectProposal: (proposalId: string) => send<RuleProposal>(rejectProposalRequest(proposalId)),

    listAlerts: (filters?: RuleAlertFilters, signal?: AbortSignal) =>
      send<RuleAlertList>(listAlertsRequest(filters), signal),
    acknowledgeAlert: (alertId: string) => send<RuleAlert>(acknowledgeAlertRequest(alertId)),

    listExecutions: (filters?: RuleExecutionFilters, signal?: AbortSignal) =>
      send<RuleExecutionList>(listExecutionsRequest(filters), signal),
  };
}
