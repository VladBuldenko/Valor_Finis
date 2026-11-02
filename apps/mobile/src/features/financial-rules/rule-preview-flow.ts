// Requesting an example for a rule (VF-020F5). One POST per call, never
// repeated here. The server owns every figure: this module validates the shape
// of the sample, sends it, checks the answer belongs to the rule version that
// was asked about, and caches it. It performs no financial arithmetic.
import type { QueryClient } from "@tanstack/react-query";

import { describeRuleError, type RuleErrorInfo } from "./financial-rule-errors.ts";
import { buildPreviewRequest } from "./financial-rule-requests.ts";
import { previewKeyFor, type PreviewInputs } from "./preview-authorization.ts";
import type { FinancialRule, RulePreview, RulePreviewRequest } from "./financial-rule.types.ts";

export const SAMPLE_AMOUNT_MESSAGE = "Enter an amount greater than zero, with at most 2 decimals.";

// Shape only (the backend stays authoritative). Null means valid.
export function validateSampleAmount(text: string): string | null {
  try {
    buildPreviewRequest(text.trim());

    return null;
  } catch {
    return SAMPLE_AMOUNT_MESSAGE;
  }
}

export type PreviewFlowResult =
  | { kind: "ok"; preview: RulePreview; inputs: PreviewInputs }
  | { kind: "invalid_input"; message: string }
  // Only INCOME_ALLOCATION rules have an example.
  | { kind: "not_previewable"; message: string }
  // The answer is for another version of the rule: it is not shown or cached.
  | { kind: "rule_changed"; message: string }
  // The session ended while the request ran: nothing is cached or shown.
  | { kind: "stale_session" }
  | { kind: "failed"; info: RuleErrorInfo };

export const RULE_EDITED_DURING_PREVIEW = "The rule changed while the example was being worked out. Show the example again.";
const NOT_PREVIEWABLE = "An example is only available for rules that reserve money from income.";
const FALLBACK = "Could not work out the example.";

export type PreviewFlowDeps = {
  queryClient: QueryClient;
  userId: string;
  rule: Pick<FinancialRule, "id" | "version" | "rule_type">;
  inputs: PreviewInputs;
  send: (ruleId: string, request: RulePreviewRequest) => Promise<RulePreview>;
  isCurrent: () => boolean;
};

export async function requestRulePreview(deps: PreviewFlowDeps): Promise<PreviewFlowResult> {
  const { queryClient, userId, rule } = deps;

  if (rule.rule_type !== "INCOME_ALLOCATION") {
    return { kind: "not_previewable", message: NOT_PREVIEWABLE };
  }

  const inputs: PreviewInputs = { amount: deps.inputs.amount.trim(), source: deps.inputs.source };
  let request: RulePreviewRequest;

  try {
    request = buildPreviewRequest(inputs.amount, inputs.source ?? undefined);
  } catch {
    return { kind: "invalid_input", message: SAMPLE_AMOUNT_MESSAGE };
  }

  let preview: RulePreview;

  try {
    preview = await deps.send(rule.id, request);
  } catch (error) {
    if (!deps.isCurrent()) {
      return { kind: "stale_session" };
    }

    // A preview changes nothing on the server, so a lost answer is a plain
    // failure the user may retry by hand; it is never retried here.
    return { kind: "failed", info: describeRuleError(error, FALLBACK) };
  }

  if (!deps.isCurrent()) {
    return { kind: "stale_session" };
  }

  if (preview.hypothetical !== true || preview.rule_id !== rule.id) {
    return { kind: "failed", info: describeRuleError(undefined, FALLBACK) };
  }

  if (preview.rule_version !== rule.version) {
    return { kind: "rule_changed", message: RULE_EDITED_DURING_PREVIEW };
  }

  queryClient.setQueryData(previewKeyFor({ userId, ruleId: rule.id, ruleVersion: rule.version, inputs }), preview);

  return { kind: "ok", preview, inputs };
}
