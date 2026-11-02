// What the preview screen shows (VF-020F5), as plain data. Every figure is the
// backend's decimal string, passed through untouched: this file never parses,
// adds, subtracts, rounds or redistributes an amount.
import { COPY } from "./financial-rule-copy.ts";
import {
  executionModeInfo,
  previewEffectText,
  previewNoticeTexts,
  previewOutcomeInfo,
  reasonText,
  type OutcomeInfo,
} from "./financial-rule-presentation.ts";
import type { RulePreview } from "./financial-rule.types.ts";

export type PreviewRow = { key: string; goal: string; planned: string; selected: string };

export type PreviewView = {
  label: string;
  heading: string;
  ruleLine: string;
  serverDate: string;
  computedAt: string;
  outcome: OutcomeInfo;
  reason: string | null;
  effect: string;
  sourceNotice: string | null;
  rows: PreviewRow[];
  planned: string;
  selected: string;
  accountFigures: { label: string; value: string }[];
  notices: string[];
};

export function buildPreviewView(
  preview: RulePreview,
  ruleName: string,
  goalName: (goalId: string) => string | null,
): PreviewView {
  const currency = preview.capacity.currency;
  const money = (value: string): string => `${value} ${currency}`;
  const sample = preview.sample_income;

  return {
    label: COPY.previewLabel,
    heading: `If you received ${money(sample.amount)}`,
    ruleLine: `${ruleName} - ${executionModeInfo(preview.execution_mode).label} - version ${preview.rule_version}`,
    serverDate: preview.as_of_date,
    computedAt: preview.computed_at,
    outcome: previewOutcomeInfo(preview.predicted_outcome),
    reason: reasonText(preview.reason_code),
    effect: previewEffectText(preview.effect) ?? COPY.previewNoAllocation,
    sourceNotice: sample.source_selected_by_rule === false ? COPY.previewSourceNotUsed : null,
    // The server's order, not re-sorted.
    rows: preview.items.map((item) => ({
      key: `${item.position}-${item.goal_id}`,
      goal: goalName(item.goal_id) ?? "Goal",
      planned: money(item.planned_amount),
      selected: money(item.selected_amount),
    })),
    planned: money(preview.planned_total),
    selected: money(preview.selected_total),
    accountFigures: [
      { label: "Available to reserve today", value: money(preview.capacity.actual_reservable) },
      { label: "Example income counted", value: money(preview.capacity.assumed_income_credit) },
      { label: "Available to reserve with the example", value: money(preview.capacity.hypothetical_reservable) },
      { label: COPY.floorLabel, value: money(preview.capacity.minimum_unallocated_floor) },
      { label: COPY.holdsLabel, value: money(preview.capacity.active_rule_holds) },
      { label: COPY.ruleCapacityLabel, value: money(preview.capacity.rule_capacity) },
    ],
    notices: previewNoticeTexts(preview.notices),
  };
}

export type TurnOnFacts = {
  isAutoAllocation: boolean;
  statusOffersEnable: boolean;
  hasShownPreview: boolean;
  outOfDate: boolean;
  inputsMatchShown: boolean;
  hasValidProof: boolean;
  busy: boolean;
};

// The reason the "Turn on automatic rule" control is disabled, or null when it
// may be used. The runner re-checks the proof itself; this only drives the UI.
export function turnOnBlockReason(facts: TurnOnFacts): string | null {
  if (!facts.isAutoAllocation) {
    return COPY.previewAutoOnly;
  }

  if (!facts.statusOffersEnable) {
    return COPY.previewTurnOnNotOffered;
  }

  if (!facts.hasShownPreview) {
    return COPY.previewTurnOnNeedsExample;
  }

  if (facts.outOfDate) {
    return COPY.previewOutOfDate;
  }

  if (!facts.inputsMatchShown) {
    return COPY.previewInputsChanged;
  }

  if (!facts.hasValidProof) {
    return COPY.previewTurnOnNeedsExample;
  }

  return facts.busy ? "Please wait." : null;
}
