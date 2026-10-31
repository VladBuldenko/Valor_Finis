// Lifecycle actions of a rule (VF-020F3): what is available, the AUTO gate,
// the guarded runner, the duplicate-submit guard and the cache plan for a
// completed change. Pure and Node-testable; screens only wire it to React.
import type { QueryClient } from "@tanstack/react-query";

import type { FinancialRulesApi } from "./financial-rule.api.ts";
import { planRuleInvalidation, type RuleInvalidationEvent } from "./financial-rule-invalidation.ts";
import { accountKeys, type QueryKeyTuple } from "./financial-rule-query-keys.ts";
import { ruleStatusInfo } from "./financial-rule-presentation.ts";
import type { FinancialRule, RuleAction } from "./financial-rule.types.ts";

export const AUTO_ENABLE_BLOCKED_MESSAGE =
  "Turning on an automatic rule needs an example first. That step arrives in an upcoming update. You can switch the rule to 'Ask me first' to turn it on now.";

export type Availability = { available: boolean; reason: string | null };

export type RuleActionAvailability = Record<RuleAction | "edit" | "delete", Availability>;

const yes: Availability = { available: true, reason: null };

// AUTO allocation rules cannot be turned on until Preview exists (F5). This is
// the single predicate used by the screen AND by the runner below.
export function isAutoEnableBlocked(rule: FinancialRule): boolean {
  return rule.rule_type === "INCOME_ALLOCATION" && rule.execution_mode === "AUTO";
}

export function getRuleActionAvailability(rule: FinancialRule): RuleActionAvailability {
  const info = ruleStatusInfo(rule.status);
  const offered = (action: RuleAction): boolean => info.actions.includes(action);
  const unavailable = (reason: string): Availability => ({ available: false, reason });

  return {
    enable: !offered("enable")
      ? unavailable("The rule is already on.")
      : isAutoEnableBlocked(rule)
        ? unavailable(AUTO_ENABLE_BLOCKED_MESSAGE)
        : yes,
    pause: offered("pause") ? yes : unavailable("Only a rule that is on can be paused."),
    disable: offered("disable") ? yes : unavailable("Only a rule that is on or paused can be turned off."),
    edit: yes,
    delete: info.canDelete ? yes : unavailable("Turn the rule off before deleting it."),
  };
}

export class ActionBlockedError extends Error {
  readonly reason: string;

  constructor(reason: string) {
    super(reason);
    this.name = "ActionBlockedError";
    this.reason = reason;
  }
}

type ActionApi = Pick<FinancialRulesApi, "enableRule" | "pauseRule" | "disableRule" | "deleteRule">;

// The ONLY way screens change a rule's status. It re-checks availability, so
// even a UI that wrongly shows a button cannot send an AUTO enable (or any
// transition the status machine does not offer) to the API.
export function createRuleActionRunner(api: ActionApi) {
  return {
    async run(rule: FinancialRule, action: RuleAction): Promise<FinancialRule> {
      const availability = getRuleActionAvailability(rule)[action];

      if (!availability.available) {
        throw new ActionBlockedError(availability.reason ?? "This action is not available.");
      }

      switch (action) {
        case "enable":
          return api.enableRule(rule.id);
        case "pause":
          return api.pauseRule(rule.id);
        case "disable":
          return api.disableRule(rule.id);
        default: {
          const exhaustive: never = action;

          throw new ActionBlockedError(String(exhaustive));
        }
      }
    },
    async remove(rule: FinancialRule): Promise<void> {
      const availability = getRuleActionAvailability(rule).delete;

      if (!availability.available) {
        throw new ActionBlockedError(availability.reason ?? "This rule cannot be deleted.");
      }

      await api.deleteRule(rule.id);
    },
  };
}

// One in-flight submit at a time. Checked synchronously in the press handler,
// so two quick taps cannot both pass before React re-renders.
export function createSubmitGuard() {
  let busy = false;

  return {
    tryEnter(): boolean {
      if (busy) {
        return false;
      }

      busy = true;

      return true;
    },
    leave(): void {
      busy = false;
    },
    isBusy: () => busy,
  };
}

export type RuleChange =
  | { kind: "created"; rule: FinancialRule }
  | { kind: "edited"; rule: FinancialRule; material: boolean }
  | { kind: "deleted"; rule: FinancialRule }
  | { kind: "status"; rule: FinancialRule; action: RuleAction };

function toEvent(change: RuleChange): RuleInvalidationEvent {
  switch (change.kind) {
    case "created":
      return { type: "rule_created" };
    case "edited":
      return { type: "rule_edited", ruleId: change.rule.id, material: change.material };
    case "deleted":
      return { type: "rule_deleted", ruleId: change.rule.id };
    case "status":
      return { type: "rule_status_changed", ruleId: change.rule.id, action: change.action };
  }
}

// The F1 set for the change, plus Accounts when a floor rule changed: the
// Account read model (minimum_unallocated_floor, rule_capacity) depends on the
// enabled floor rule. A new draft floor contributes 0.00, so create adds nothing.
export function planRuleChangeInvalidation(userId: string, change: RuleChange): QueryKeyTuple[] {
  const keys = planRuleInvalidation(userId, toEvent(change));

  if (change.rule.rule_type === "MINIMUM_UNALLOCATED_FLOOR" && change.kind !== "created") {
    const accounts = accountKeys.family(userId);

    if (!keys.some((key) => JSON.stringify(key) === JSON.stringify(accounts))) {
      keys.push(accounts);
    }
  }

  return keys;
}

export function applyRuleChangeInvalidation(
  queryClient: QueryClient,
  userId: string,
  change: RuleChange,
): Promise<unknown> {
  return Promise.all(
    planRuleChangeInvalidation(userId, change).map((queryKey) =>
      queryClient.invalidateQueries({ queryKey: [...queryKey] }),
    ),
  );
}
