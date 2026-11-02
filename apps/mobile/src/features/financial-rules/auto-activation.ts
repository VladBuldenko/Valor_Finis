// Turning an AUTO rule on (VF-020F5). One enable POST per call, never resent.
// The runner (financial-rule-actions.ts) independently enforces the preview
// gate; this module adds the outcome handling around it:
//   - a refusal before any POST (no valid preview, rule changed, session
//     changed, the re-read failed) changes nothing and asks for a new example;
//   - a definite answer from the server is shown as the authoritative status;
//   - when the POST's outcome is unknown (timeout, lost connection, unreadable
//     answer, 5xx) the rule is read back ONCE; nothing is claimed beyond that.
import { isApiError } from "../../api/api-error.ts";
import { COPY } from "./financial-rule-copy.ts";
import {
  ActionBlockedError,
  ActionPreflightError,
  ActionStaleError,
  SESSION_CHANGED_MESSAGE,
  type RuleChange,
} from "./financial-rule-actions.ts";
import { describeRuleError, type RuleErrorInfo } from "./financial-rule-errors.ts";
import { isAmbiguous } from "./inbox-proposal-actions.ts";
import type { PreviewProof } from "./preview-authorization.ts";
import type { FinancialRule } from "./financial-rule.types.ts";

export type ActivationResult =
  // The server answered; `rule.status` is the authority (normally "enabled").
  | { kind: "activated"; rule: FinancialRule }
  // The server answered with a status other than "enabled".
  | { kind: "unexpected_status"; rule: FinancialRule }
  // Nothing was sent: a new example is needed (or the session is gone).
  | { kind: "needs_new_preview"; message: string }
  | { kind: "session_changed" }
  // Nothing was sent: the re-read before enabling failed.
  | { kind: "not_checked"; info: RuleErrorInfo }
  // A definite failure from the server; the rule was not turned on.
  | { kind: "failed"; info: RuleErrorInfo }
  // The POST's outcome was unknown and the read-back showed the rule is on.
  | { kind: "unknown_resolved"; rule: FinancialRule }
  | { kind: "unknown_pending"; rule: FinancialRule | null; message: string };

export type ActivationDeps = {
  rule: FinancialRule;
  proof: PreviewProof | undefined;
  run: (rule: FinancialRule, proof: PreviewProof | undefined) => Promise<FinancialRule>;
  // The one follow-up request, after an unknown outcome.
  readBack: (ruleId: string) => Promise<FinancialRule>;
  isCurrent: () => boolean;
  invalidate: (change: RuleChange) => Promise<unknown> | void;
};

const FALLBACK = "Unable to turn the rule on.";
const NOT_CHECKED = "We could not check the rule, so nothing was turned on. Try again.";

async function refresh(deps: ActivationDeps, change: RuleChange): Promise<void> {
  if (deps.isCurrent()) {
    await deps.invalidate(change);
  }
}

export async function activateAutoRule(deps: ActivationDeps): Promise<ActivationResult> {
  if (!deps.isCurrent()) {
    return { kind: "session_changed" };
  }

  let updated: FinancialRule;

  try {
    updated = await deps.run(deps.rule, deps.proof);
  } catch (error) {
    if (error instanceof ActionStaleError) {
      return { kind: "needs_new_preview", message: error.reason };
    }

    if (error instanceof ActionBlockedError) {
      return error.reason === SESSION_CHANGED_MESSAGE
        ? { kind: "session_changed" }
        : { kind: "needs_new_preview", message: error.reason };
    }

    if (error instanceof ActionPreflightError) {
      return { kind: "not_checked", info: describeRuleError(error.cause, NOT_CHECKED) };
    }

    if (isAmbiguous(error)) {
      let current: FinancialRule | null = null;

      try {
        current = await deps.readBack(deps.rule.id);
      } catch {
        current = null;
      }

      // The write may or may not have happened: refresh what a status change touches.
      await refresh(deps, { kind: "status", rule: current ?? deps.rule, action: "enable" });

      if (current !== null && current.status === "enabled") {
        return { kind: "unknown_resolved", rule: current };
      }

      return { kind: "unknown_pending", rule: current, message: COPY.outcomeUnknown };
    }

    await refresh(deps, { kind: "status", rule: deps.rule, action: "enable" });

    return {
      kind: "failed",
      info: describeRuleError(isApiError(error) ? error : undefined, FALLBACK, { mutation: true }),
    };
  }

  await refresh(deps, { kind: "status", rule: updated, action: "enable" });

  return updated.status === "enabled" ? { kind: "activated", rule: updated } : { kind: "unexpected_status", rule: updated };
}

export const AUTO_ACTIVATION_DIALOG = {
  title: "Turn on automatic reservations?",
  button: "Turn on",
  // Each line is a separate sentence on purpose (decision record C1, C2, C8).
  lines: [
    "This rule can set money aside for your Goals without asking you to confirm each eligible income.",
    "No bank transfer takes place.",
    "A reservation is an earmark inside an Account.",
    "Rules are checked when you open or refresh the app and after you record income. Nothing is checked at other times.",
    "The example was hypothetical. What actually happens may differ.",
  ],
} as const;

export const autoActivationMessage = AUTO_ACTIVATION_DIALOG.lines.join("\n\n");
