// Confirm / decline of a proposal (VF-020F4). One POST per call, never
// repeated here. The result always comes from the RETURNED proposal status
// (rule C5); when the outcome of a POST is unknown or the proposal went stale,
// the authoritative state is read back with a GET before anything is claimed.
import { isApiError } from "../../api/api-error.ts";
import { COPY } from "./financial-rule-copy.ts";
import { describeRuleError, type RuleErrorInfo } from "./financial-rule-errors.ts";
import { planRuleInvalidation, type RuleInvalidationEvent } from "./financial-rule-invalidation.ts";
import { proposalOutcome, type ProposalDecision, type ProposalOutcome } from "./financial-rule-presentation.ts";
import type { QueryKeyTuple } from "./financial-rule-query-keys.ts";
import type { RuleProposal } from "./financial-rule.types.ts";

export type DecisionResult =
  // The server answered with a proposal; its status is the outcome.
  | { kind: "decided"; proposal: RuleProposal; outcome: ProposalOutcome }
  // 409 stale: the proposal was cancelled; the refetched state (or null) is shown.
  | { kind: "stale"; proposal: RuleProposal | null; message: string }
  // The POST's outcome was unknown; the refetch resolved it (status other than
  // awaiting) or did not.
  | { kind: "unknown_resolved"; proposal: RuleProposal; outcome: ProposalOutcome }
  | { kind: "unknown_pending"; proposal: RuleProposal | null; message: string }
  // A definite failure that changed nothing (404, validation, ...).
  | { kind: "failed"; info: RuleErrorInfo };

export type DecisionDeps = {
  decision: ProposalDecision;
  send: () => Promise<RuleProposal>;
  // A GET of the proposal; the only follow-up request this module makes.
  refetch: () => Promise<RuleProposal>;
  // False once the user/session that started this is gone.
  isCurrent: () => boolean;
  // Receives the invalidation plan to apply (only while still current).
  invalidate: (keys: QueryKeyTuple[]) => Promise<unknown> | void;
  userId: string;
};

const FALLBACK = "Unable to complete that.";

export function isAmbiguous(error: unknown): boolean {
  if (!isApiError(error)) {
    return true;
  }

  return (
    error.kind === "timeout" ||
    error.kind === "network" ||
    error.kind === "malformed_response" ||
    (error.kind === "http" && error.status !== null && error.status >= 500)
  );
}

async function readBack(deps: DecisionDeps): Promise<RuleProposal | null> {
  try {
    return await deps.refetch();
  } catch {
    return null;
  }
}

async function refresh(deps: DecisionDeps, event: RuleInvalidationEvent): Promise<void> {
  if (deps.isCurrent()) {
    await deps.invalidate(planRuleInvalidation(deps.userId, event));
  }
}

export async function decideProposal(deps: DecisionDeps): Promise<DecisionResult> {
  let proposal: RuleProposal;

  try {
    proposal = await deps.send();
  } catch (error) {
    if (isApiError(error) && error.code === "rule_proposal_stale") {
      // The backend may have committed the cancellation: read the truth back.
      const current = await readBack(deps);

      await refresh(deps, { type: "proposal_decided", decision: deps.decision, status: current?.status ?? "cancelled" });

      return { kind: "stale", proposal: current, message: describeRuleError(error, FALLBACK, { mutation: true }).message };
    }

    if (isAmbiguous(error)) {
      const current = await readBack(deps);

      if (current && current.status !== "awaiting_confirmation") {
        await refresh(deps, { type: "proposal_decided", decision: deps.decision, status: current.status });

        return { kind: "unknown_resolved", proposal: current, outcome: proposalOutcome(deps.decision, current.status) };
      }

      // Could still have happened or not: refresh everything a confirm touches.
      await refresh(deps, { type: "proposal_decided", decision: deps.decision, status: "executed" });

      return { kind: "unknown_pending", proposal: current, message: COPY.outcomeUnknown };
    }

    await refresh(deps, { type: "proposal_decided", decision: deps.decision, status: "awaiting_confirmation" });

    return { kind: "failed", info: describeRuleError(error, FALLBACK, { mutation: true }) };
  }

  await refresh(deps, { type: "proposal_decided", decision: deps.decision, status: proposal.status });

  return { kind: "decided", proposal, outcome: proposalOutcome(deps.decision, proposal.status) };
}

export const CONFIRM_DIALOG = {
  title: "Reserve these amounts?",
  message:
    "This sets money aside inside the Account for your Goals. It does not move any money in your bank.",
  button: "Reserve",
} as const;

export const REJECT_DIALOG = {
  title: "Decline this suggestion?",
  message: "Nothing will be reserved.",
  button: "Decline",
} as const;

export const HOLD_EXPLANATION =
  "A suggestion holds part of your Account's capacity for rules. Nothing is reserved until you confirm.";
