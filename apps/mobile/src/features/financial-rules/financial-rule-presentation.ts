// Pure mappers from API values to what a screen shows (VF-020F1): statuses,
// lifecycle, reason codes, alert levels, preview notices and proposal
// outcomes. Every union is mapped with an exhaustive switch, so adding a
// member to a type fails the compile until its wording exists. Values that
// arrive from the server as plain strings (reason codes, notices) go through
// a guard and a safe fallback instead - an unknown value is never rendered raw.
import { COPY, MODE_COPY, POLICY_COPY, RULE_TYPE_COPY } from "./financial-rule-copy.ts";
import {
  ALERT_LEVELS,
  assertNever,
  type AlertLevel,
  type ExecutionMode,
  type ExecutionStatus,
  type PreviewEffect,
  type PreviewOutcome,
  type ProposalStatus,
  type RuleAction,
  type RuleAlert,
  type RulePolicy,
  type RuleStatus,
  type RuleType,
} from "./financial-rule.types.ts";

export type Tone = "neutral" | "positive" | "attention" | "negative";

// -------------------------------------------------------- rule lifecycle

export type RuleStatusInfo = {
  label: string;
  tone: Tone;
  // Actions the status machine offers from this status. The server stays
  // authoritative (e.g. enable can still be refused); this only drives menus.
  actions: readonly RuleAction[];
  // Delete is only offered for draft and disabled rules; a rule that ever
  // executed is still refused by the server (409).
  canDelete: boolean;
};

export function ruleStatusInfo(status: RuleStatus): RuleStatusInfo {
  switch (status) {
    case "draft":
      return { label: "Draft", tone: "neutral", actions: ["enable"], canDelete: true };
    case "enabled":
      return { label: "On", tone: "positive", actions: ["pause", "disable"], canDelete: false };
    case "paused":
      return { label: "Paused", tone: "attention", actions: ["enable", "disable"], canDelete: false };
    case "disabled":
      return { label: "Off", tone: "neutral", actions: ["enable"], canDelete: true };
    default:
      return assertNever(status, "rule status");
  }
}

// What the status becomes after a successful action.
export function statusAfterAction(action: RuleAction): RuleStatus {
  switch (action) {
    case "enable":
      return "enabled";
    case "pause":
      return "paused";
    case "disable":
      return "disabled";
    default:
      return assertNever(action, "rule action");
  }
}

export function ruleActionLabel(action: RuleAction): string {
  switch (action) {
    case "enable":
      return "Turn on";
    case "pause":
      return "Pause";
    case "disable":
      return "Turn off";
    default:
      return assertNever(action, "rule action");
  }
}

export const ruleTypeLabel = (type: RuleType): string => RULE_TYPE_COPY[type].label;
export const executionModeInfo = (mode: ExecutionMode) => MODE_COPY[mode];
export const rulePolicyLabel = (policy: RulePolicy): string => POLICY_COPY[policy].label;

// A material rule edit bumps `version`, which invalidates previews. These are
// the PATCH fields that are NOT material (backend MATERIAL_SCALAR_FIELDS):
// name, description and evaluation order; every other field changes the
// rule's financial meaning.
const NON_MATERIAL_FIELDS: ReadonlySet<string> = new Set([
  "name",
  "description",
  "execution_order",
]);

export function isMaterialRuleEdit(changedFields: readonly string[]): boolean {
  return changedFields.some((field) => !NON_MATERIAL_FIELDS.has(field));
}

// ------------------------------------------------------------- statuses

export type OutcomeInfo = { label: string; tone: Tone };

export function executionStatusInfo(status: ExecutionStatus): OutcomeInfo {
  switch (status) {
    case "awaiting_confirmation":
      return { label: "Waiting for you", tone: "attention" };
    case "executed":
      return { label: "Reserved", tone: "positive" };
    case "executed_partial":
      return { label: "Partly reserved", tone: "positive" };
    case "skipped":
      return { label: "Skipped", tone: "neutral" };
    case "blocked":
      return { label: "Blocked", tone: "negative" };
    case "rejected":
      return { label: "Declined", tone: "neutral" };
    case "expired":
      return { label: "Expired", tone: "neutral" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral" };
    default:
      return assertNever(status, "execution status");
  }
}

export function proposalStatusInfo(status: ProposalStatus): OutcomeInfo {
  switch (status) {
    case "awaiting_confirmation":
    case "executed":
    case "executed_partial":
    case "rejected":
    case "expired":
    case "cancelled":
      return executionStatusInfo(status);
    default:
      return assertNever(status, "proposal status");
  }
}

// A proposal can still be confirmed or declined only while it is waiting.
export const isProposalActionable = (status: ProposalStatus): boolean =>
  status === "awaiting_confirmation";

export type ProposalDecision = "confirm" | "reject";

export type ProposalOutcome = {
  // What happened, read from the RETURNED status (rule C5), not the HTTP code.
  status: ProposalStatus;
  message: string;
  tone: Tone;
  // False when the result is not what the user asked for (e.g. they confirmed
  // and the proposal had already expired); the screen must say so.
  matchesRequest: boolean;
};

export function proposalOutcome(decision: ProposalDecision, status: ProposalStatus): ProposalOutcome {
  switch (status) {
    case "executed":
      return {
        status,
        message: "Reserved for your Goals.",
        tone: "positive",
        matchesRequest: decision === "confirm",
      };
    case "executed_partial":
      return {
        status,
        message: "Partly reserved: only part of the amount fit.",
        tone: "positive",
        matchesRequest: decision === "confirm",
      };
    case "rejected":
      return {
        status,
        message: "Suggestion declined. Nothing was reserved.",
        tone: "neutral",
        matchesRequest: decision === "reject",
      };
    case "expired":
      return {
        status,
        message: "This suggestion had already expired. Nothing was reserved.",
        tone: "attention",
        matchesRequest: false,
      };
    case "cancelled":
      return {
        status,
        message: "This suggestion was cancelled. Nothing was reserved.",
        tone: "attention",
        matchesRequest: false,
      };
    case "awaiting_confirmation":
      return {
        status,
        message: "This suggestion is still waiting for your decision.",
        tone: "attention",
        matchesRequest: false,
      };
    default:
      return assertNever(status, "proposal status");
  }
}

// ---------------------------------------------------------- reason codes

// Codes the backend writes to `reason_code` today: the planner's five, the
// not-eligible source reason shared with preview, and the cancellation reasons.
const REASON_COPY = {
  insufficient_capacity:
    "There was not enough available to reserve after the minimum unallocated amount and other pending suggestions.",
  nothing_to_allocate: "The rule had nothing to reserve for this income.",
  source_account_archived: "The Account this rule uses is archived.",
  target_goal_archived: "A Goal this rule targets is archived.",
  currency_mismatch: "The Account and a Goal use different currencies.",
  income_source_not_selected: "This income's source is not one the rule applies to.",
  superseded: "The rule was edited, so this suggestion was replaced.",
  stale: "The figures changed, so this suggestion was cancelled. Nothing was reserved.",
  source_changed: "The income was changed after this suggestion was made, so it was cancelled.",
  source_deleted: "The income was deleted, so this suggestion was cancelled.",
  rule_inactive: "The rule was paused or turned off, so this suggestion was cancelled.",
} as const;

export type KnownReasonCode = keyof typeof REASON_COPY;

export const KNOWN_REASON_CODES = Object.keys(REASON_COPY) as KnownReasonCode[];

export function isKnownReasonCode(code: string): code is KnownReasonCode {
  return Object.prototype.hasOwnProperty.call(REASON_COPY, code);
}

// null means "no reason recorded"; an unknown code gets the generic text and
// is never echoed to the user.
export function reasonText(code: string | null): string | null {
  if (code === null) {
    return null;
  }

  return isKnownReasonCode(code) ? REASON_COPY[code] : COPY.fallbackReason;
}

// ------------------------------------------------------------- alerts

export type AlertLevelInfo = { label: string; tone: Tone; severity: number };

export function alertLevelInfo(level: AlertLevel): AlertLevelInfo {
  switch (level) {
    case "watch":
      return { label: "Keep an eye on it", tone: "attention", severity: 1 };
    case "at_risk":
      return { label: "At risk", tone: "attention", severity: 2 };
    case "exceeded":
      return { label: "Over the limit", tone: "negative", severity: 3 };
    case "breached":
      return { label: "Below the minimum", tone: "negative", severity: 3 };
    default:
      return assertNever(level, "alert level");
  }
}

export function isAlertLevel(value: string): value is AlertLevel {
  return (ALERT_LEVELS as readonly string[]).includes(value);
}

const NEUTRAL_ALERT_LEVEL: AlertLevelInfo = { label: "Needs attention", tone: "attention", severity: 1 };

// For a level the app does not know (a newer server): a safe neutral label.
export function alertLevelInfoOrFallback(level: string): AlertLevelInfo {
  return isAlertLevel(level) ? alertLevelInfo(level) : NEUTRAL_ALERT_LEVEL;
}

export function alertMessage(alert: Pick<RuleAlert, "rule_type" | "subject_type" | "subject_name" | "level">): string {
  const name = alert.subject_name ?? (alert.subject_type === "account" ? "A deleted Account" : "A deleted Budget");

  switch (alert.rule_type) {
    case "MINIMUM_UNALLOCATED_FLOOR":
      return `${name} is below its minimum unallocated amount.`;
    case "OVERCOMMITMENT_ALERT":
      return `${name} has more reserved for Goals than it can cover.`;
    case "BUDGET_ALERT":
      return budgetAlertMessage(name, alert.level);
    default:
      return assertNever(alert.rule_type, "alert rule type");
  }
}

function budgetAlertMessage(name: string, level: AlertLevel): string {
  switch (level) {
    case "watch":
      return `${name} is getting close to its limit.`;
    case "at_risk":
      return `${name} is at risk of going over its limit.`;
    case "exceeded":
      return `${name} has gone over its limit.`;
    case "breached":
      // Account episodes use "breached"; a Budget alert never does.
      return `${name} needs attention.`;
    default:
      return assertNever(level, "alert level");
  }
}

// An alert is open until acknowledged; "resolved" only says the Account recovered.
export const isAlertOpen = (alert: Pick<RuleAlert, "acknowledged_at">): boolean =>
  alert.acknowledged_at === null;

// ------------------------------------------------------------- preview

export function previewOutcomeInfo(outcome: PreviewOutcome): OutcomeInfo {
  switch (outcome) {
    case "full":
      return { label: "Everything would fit", tone: "positive" };
    case "partial":
      return { label: "Only part would fit", tone: "attention" };
    case "skipped":
      return { label: "Nothing would be reserved", tone: "neutral" };
    case "blocked":
      return { label: "The rule could not run", tone: "negative" };
    default:
      return assertNever(outcome, "preview outcome");
  }
}

export function previewEffectText(effect: PreviewEffect): string | null {
  switch (effect) {
    case "would_apply":
      return COPY.previewWouldApply;
    case "would_hold":
      return COPY.previewWouldHold;
    case "none":
      return null;
    default:
      return assertNever(effect, "preview effect");
  }
}

const NOTICE_COPY = {
  hypothetical_snapshot: COPY.previewDisclaimer,
  income_not_recorded: COPY.previewIncomeNotRecorded,
  real_event_eligibility_not_simulated: COPY.previewEligibilityNotSimulated,
  other_enabled_rules_not_simulated: COPY.previewOtherRulesNotSimulated,
  rule_not_enabled: COPY.previewRuleNotEnabled,
} as const;

function isKnownNotice(token: string): token is keyof typeof NOTICE_COPY {
  return Object.prototype.hasOwnProperty.call(NOTICE_COPY, token);
}

// Known notices in the server's order; unknown tokens are dropped (never shown
// raw). The hypothetical disclaimer is ALWAYS first, even if the server omitted
// it, so a preview cannot be shown without its label (rule C8).
export function previewNoticeTexts(notices: readonly string[]): string[] {
  const known = notices.filter(isKnownNotice).map((token) => NOTICE_COPY[token]);

  return known.includes(COPY.previewDisclaimer) ? known : [COPY.previewDisclaimer, ...known];
}
