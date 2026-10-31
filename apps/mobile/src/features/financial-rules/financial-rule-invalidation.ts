// Exact cache-invalidation sets of the Smart Rules feature (VF-020F1).
//
// planRuleInvalidation() is pure: an event in, the list of query-key PREFIXES
// out. applyRuleInvalidation() hands each prefix to invalidateQueries. Nothing
// is ever cleared or removed, and only the families named below are touched:
// Expenses, Income, Budgets, Transfers and the other analytics are never
// invalidated by a rule event.
//
// Server-state truth always comes from a refetch; no balance or capacity is
// computed or patched locally.
import type { QueryClient } from "@tanstack/react-query";

import { accountKeys, financialRuleKeys, goalKeys, type QueryKeyTuple } from "./financial-rule-query-keys.ts";
import {
  assertNever,
  type ProposalStatus,
  type RuleAction,
  type RuleEvaluationResult,
} from "./financial-rule.types.ts";

export type RuleInvalidationEvent =
  | { type: "rule_created" }
  | { type: "rule_edited"; ruleId: string; material: boolean }
  | { type: "rule_deleted"; ruleId: string }
  | { type: "rule_status_changed"; ruleId: string; action: RuleAction }
  // `status` is the status RETURNED by the server, not the HTTP code (rule C5).
  | { type: "proposal_decided"; decision: "confirm" | "reject"; status: ProposalStatus }
  | { type: "alert_acknowledged" }
  | { type: "evaluated"; result: RuleEvaluationResult }
  | { type: "goal_or_account_changed" }
  | { type: "income_recorded" };

// True when the evaluation may have changed anything the screens show.
export function evaluationChangedState(result: RuleEvaluationResult): boolean {
  return (
    result.processed > 0 ||
    result.failed_retryable > 0 ||
    result.dead > 0 ||
    result.alerts_created > 0 ||
    result.alerts_resolved > 0 ||
    Object.keys(result.outcomes).length > 0
  );
}

export function planRuleInvalidation(userId: string, event: RuleInvalidationEvent): QueryKeyTuple[] {
  const rules = financialRuleKeys.rulesFamily(userId);
  const proposals = financialRuleKeys.proposalsFamily(userId);
  const alerts = financialRuleKeys.alertsFamily(userId);
  const executions = financialRuleKeys.executionsFamily(userId);
  const previews = financialRuleKeys.previewsFamily(userId);
  const goals = goalKeys.family(userId);
  const goalProgress = goalKeys.progress(userId);
  const accounts = accountKeys.family(userId);

  switch (event.type) {
    case "rule_created":
      // A new draft changes only the list; nothing else refers to it yet.
      return [rules];

    case "rule_edited":
      // A material edit bumps the version and cancels open proposals of the
      // old version (releasing their holds on the Account); a name or
      // description edit changes neither.
      return event.material
        ? [rules, financialRuleKeys.previewsOfRule(userId, event.ruleId), proposals, executions, accounts]
        : [rules];

    case "rule_deleted":
      // Only a draft or disabled rule without executions can be deleted.
      return [rules, financialRuleKeys.previewsOfRule(userId, event.ruleId)];

    case "rule_status_changed":
      switch (event.action) {
        case "enable":
          // Enabling resets active_since and may set effective_from; the
          // rule_status of existing previews changes with it.
          return [rules, financialRuleKeys.previewsOfRule(userId, event.ruleId)];
        case "pause":
        case "disable":
          // Open proposals of the rule are cancelled and their holds released.
          return [rules, financialRuleKeys.previewsOfRule(userId, event.ruleId), proposals, executions, accounts];
        default:
          return assertNever(event.action, "rule action");
      }

    case "proposal_decided":
      switch (event.status) {
        case "executed":
        case "executed_partial":
          // Money was reserved to Goals: Goal amounts, Goal Progress and the
          // Account's reserved/reservable all changed.
          return [proposals, executions, goals, goalProgress, accounts];
        case "rejected":
        case "expired":
        case "cancelled":
          // Nothing was reserved; the hold on the Account's capacity ended.
          return [proposals, executions, accounts];
        case "awaiting_confirmation":
          // Not a decided outcome: refresh the proposals only.
          return [proposals];
        default:
          return assertNever(event.status, "proposal status");
      }

    case "alert_acknowledged":
      return [alerts];

    case "evaluated": {
      if (!evaluationChangedState(event.result)) {
        return [];
      }

      // Executions may have created proposals/alerts or reserved money.
      const keys: QueryKeyTuple[] = [proposals, executions];

      if (event.result.alerts_created > 0 || event.result.alerts_resolved > 0) {
        keys.push(alerts);
      }

      if (Object.keys(event.result.outcomes).length > 0) {
        keys.push(goals, goalProgress, accounts);
      }

      return keys;
    }

    case "goal_or_account_changed":
      // Previews and proposals embed Goal and Account figures that just moved.
      return [previews, proposals];

    case "income_recorded":
      // The sample a preview assumed is now (partly) real; the actual drain
      // happens on evaluate, which invalidates what it changed.
      return [previews];

    default:
      return assertNever(event, "rule invalidation event");
  }
}

export function applyRuleInvalidation(
  queryClient: QueryClient,
  userId: string,
  event: RuleInvalidationEvent,
): Promise<unknown> {
  return Promise.all(
    planRuleInvalidation(userId, event).map((queryKey) =>
      queryClient.invalidateQueries({ queryKey: [...queryKey] }),
    ),
  );
}
