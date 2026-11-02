// Lifecycle actions of a rule (VF-020F3): what is available, the AUTO gate,
// the guarded runner, the duplicate-submit guard and the cache plan for a
// completed change. Pure and Node-testable; screens only wire it to React.
import type { QueryClient } from "@tanstack/react-query";

import type { FinancialRulesApi } from "./financial-rule.api.ts";
import type { PreviewProof } from "./preview-authorization.ts";
import { planRuleInvalidation, type RuleInvalidationEvent } from "./financial-rule-invalidation.ts";
import { accountKeys, type QueryKeyTuple } from "./financial-rule-query-keys.ts";
import { ruleStatusInfo } from "./financial-rule-presentation.ts";
import type { FinancialRule, RuleAction } from "./financial-rule.types.ts";

export const AUTO_ENABLE_BLOCKED_MESSAGE =
  "Turning on an automatic rule needs an example first. Look at the example for this version of the rule, or switch the rule to 'Ask me first' to turn it on now.";
export const RULE_CHANGED_MESSAGE = "The rule changed since the example. Show the example again.";
export const SESSION_CHANGED_MESSAGE = "Your session changed. Nothing was turned on.";

export type Availability = { available: boolean; reason: string | null };

export type RuleActionAvailability = Record<RuleAction | "edit" | "delete", Availability>;

const yes: Availability = { available: true, reason: null };

// An AUTO allocation rule needs a viewed preview of its current version to be
// turned on (F5). This is the single predicate used by the screen AND by the
// runner below; CONFIRM and the other rule types never need a preview.
export function isAutoEnableBlocked(rule: FinancialRule): boolean {
  return rule.rule_type === "INCOME_ALLOCATION" && rule.execution_mode === "AUTO";
}

const modeOf = (rule: FinancialRule): string | null =>
  rule.rule_type === "INCOME_ALLOCATION" ? rule.execution_mode : null;

export type AvailabilityOptions = {
  // True only when a valid preview proof exists for this rule and version.
  autoAuthorized?: boolean;
};

export function getRuleActionAvailability(
  rule: FinancialRule,
  options: AvailabilityOptions = {},
): RuleActionAvailability {
  const info = ruleStatusInfo(rule.status);
  const offered = (action: RuleAction): boolean => info.actions.includes(action);
  const unavailable = (reason: string): Availability => ({ available: false, reason });

  return {
    enable: !offered("enable")
      ? unavailable("The rule is already on.")
      : isAutoEnableBlocked(rule) && options.autoAuthorized !== true
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

// The authoritative rule no longer matches what the user previewed. Nothing
// was sent; a new preview is needed.
export class ActionStaleError extends ActionBlockedError {
  constructor(reason: string = RULE_CHANGED_MESSAGE) {
    super(reason);
    this.name = "ActionStaleError";
  }
}

// The pre-enable re-read failed. Nothing was sent, so this is NOT an unknown
// outcome: the enable POST never happened.
export class ActionPreflightError extends Error {
  readonly cause: unknown;

  constructor(cause: unknown) {
    super("The rule could not be re-checked before turning it on.");
    this.name = "ActionPreflightError";
    this.cause = cause;
  }
}

type ActionApi = Pick<FinancialRulesApi, "enableRule" | "pauseRule" | "disableRule" | "deleteRule"> &
  Partial<Pick<FinancialRulesApi, "getRule">>;

export type AutoGate = {
  verify(proof: PreviewProof | undefined, rule: Pick<FinancialRule, "id" | "version">): boolean;
  revokeRule(ruleId: string): void;
};

export type RunOptions = {
  // Required (and verified) to turn an AUTO allocation rule on.
  proof?: PreviewProof;
  // False once the user/session the call started for is gone.
  isCurrent?: () => boolean;
  signal?: AbortSignal;
};

// The ONLY way screens change a rule's status. It re-checks availability, so
// even a UI that wrongly shows a button cannot send an AUTO enable (or any
// transition the status machine does not offer) to the API. An AUTO enable
// additionally needs a valid preview proof from `gate`, re-reads the rule and
// refuses a changed version/mode/status, and checks the session again right
// before the one POST. Without a gate or a re-read capability it fails closed.
export function createRuleActionRunner(api: ActionApi, gate?: AutoGate) {
  return {
    async run(rule: FinancialRule, action: RuleAction, options: RunOptions = {}): Promise<FinancialRule> {
      const needsPreview = action === "enable" && isAutoEnableBlocked(rule);
      const authorized = !needsPreview || gate?.verify(options.proof, rule) === true;
      const availability = getRuleActionAvailability(rule, { autoAuthorized: authorized })[action];

      if (!availability.available) {
        throw new ActionBlockedError(availability.reason ?? "This action is not available.");
      }

      if (needsPreview) {
        if (gate === undefined || api.getRule === undefined) {
          throw new ActionBlockedError(AUTO_ENABLE_BLOCKED_MESSAGE);
        }

        let latest: FinancialRule;

        try {
          latest = await api.getRule(rule.id, options.signal);
        } catch (error) {
          throw new ActionPreflightError(error);
        }

        if (options.isCurrent !== undefined && !options.isCurrent()) {
          throw new ActionBlockedError(SESSION_CHANGED_MESSAGE);
        }

        const unchanged =
          latest.id === rule.id &&
          latest.rule_type === rule.rule_type &&
          latest.version === rule.version &&
          latest.status === rule.status &&
          modeOf(latest) === modeOf(rule);

        if (!unchanged || !gate.verify(options.proof, latest)) {
          gate.revokeRule(rule.id);

          throw new ActionStaleError();
        }
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
