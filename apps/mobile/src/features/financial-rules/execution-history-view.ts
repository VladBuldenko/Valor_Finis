// What one execution-history card shows (VF-020F6). Pure and Node-testable.
//
// Rules this file keeps:
//  - Every amount is the backend's decimal string, unchanged. Nothing is added,
//    subtracted, rounded, totalled or compared. A null `applied_amount` is the
//    words "Not applied", never a number.
//  - Reason codes go through `reasonText` (null stays null, unknown codes get
//    the neutral text and are never echoed). `rejected` and `expired` carry no
//    reason in the backend, so they are explained from their status.
//  - Audit rows are translated only for codes the backend is known to write;
//    `details`, ids and unknown codes or actors are never shown.
//  - Rule and Goal names are looked up NOW. They are labelled as current names
//    and a name that cannot be found is described, not guessed.
import type { EvaluationStatus } from "./financial-rule-evaluation-trigger.ts";
import { COPY } from "./financial-rule-copy.ts";
import { executionStatusInfo, reasonText } from "./financial-rule-presentation.ts";
import type { ExecutionStatus, RuleExecution, RuleExecutionAudit } from "./financial-rule.types.ts";

export const HISTORY_COPY = {
  title: "History",
  intro:
    "This list shows rule runs that were recorded. Income that has not been checked yet, or could not be checked, does not appear here.",
  paging: "Newer runs can appear while you scroll, which can move older ones down. Pull down to refresh the list.",
  signedOut: "Sign in to see your rule history.",
  loading: "Loading history",
  empty: "No rule runs yet.",
  emptyFiltered: "No runs match these filters.",
  clearFilters: "Clear filters",
  end: "That is everything.",
  stalled: "More runs exist but none could be loaded right now. Pull down to refresh.",
  invalidRuleLink: "That rule link was not valid, so all rules are shown.",
  checkIncomplete:
    "Some income could not be checked completely in this session, so recent income may be missing from this list.",
  checkFailed: "The last check did not complete, so recent income may be missing from this list.",
  allRules: "All rules",
  allStatuses: "All statuses",
  ruleFilterTitle: "Rule",
  statusFilterTitle: "Status",
  ruleFallback: "Rule",
  ruleGone: "A rule that is no longer in your list",
  goalFallback: "Goal",
  goalGone: "A Goal that is no longer in your active list",
  notApplied: "Not applied",
  notRecorded: "Not recorded",
  unknownDate: "Unknown date",
  unknownTime: "Unknown time",
  reservationRecorded: "Recorded as a Goal reservation",
  noGoals: "No Goals were part of this run.",
  waitingNote:
    "A suggestion was made and is waiting for a decision. Open the Inbox to see whether it is still open.",
  nothingReserved: "Nothing was reserved.",
  openInbox: "Open the Inbox",
  currencyNote: "Shown in the Account's currency.",
} as const;

// ------------------------------------------------------------------ dates

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

// `source_received_at` is a calendar date. It is read from its own parts, never
// through Date: new Date("2026-11-02") is UTC midnight, which is the previous
// day for a user west of UTC.
export function formatDateOnly(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

  if (match === null) {
    return HISTORY_COPY.unknownDate;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();

  if (month < 1 || month > 12 || day < 1 || day > daysInMonth) {
    return HISTORY_COPY.unknownDate;
  }

  return `${day} ${MONTHS[month - 1]} ${year}`;
}

// `created_at` / `decided_at` are instants, shown in the device's locale.
export function formatInstant(value: string): string {
  const time = Date.parse(value);

  return Number.isFinite(time) ? new Date(time).toLocaleString() : HISTORY_COPY.unknownTime;
}

// ----------------------------------------------------------------- wording

const STATUS_EXPLANATION: Record<ExecutionStatus, string> = {
  awaiting_confirmation: HISTORY_COPY.waitingNote,
  executed: "The full planned amount was reserved.",
  executed_partial: "Only part of the plan fit, so part was reserved.",
  skipped: "The rule ran but reserved nothing.",
  blocked: "The rule could not run.",
  rejected: "You declined this suggestion.",
  expired: "This suggestion was not confirmed in time.",
  cancelled: "This suggestion was cancelled.",
};

// Statuses that end without any reservation having been written.
const NOTHING_WRITTEN: ReadonlySet<ExecutionStatus> = new Set(["rejected", "expired", "cancelled"]);

export const statusExplanation = (status: ExecutionStatus): string => STATUS_EXPLANATION[status];

// The audit codes the backend writes today, each in plain language. A code
// that is not here is dropped, not echoed.
const AUDIT_COPY: Record<string, string> = {
  proposed: "Suggested to you",
  applied: "Reserved for your Goals",
  applied_partial: "Partly reserved for your Goals",
  skipped: "Skipped, nothing reserved",
  blocked: "Could not run",
  confirmed: "Confirmed",
  rejected: "Declined",
  expired: "Not confirmed in time",
  cancelled: "Cancelled",
  source_changed: "The income was changed after this ran. This record shows what happened at the time.",
  source_deleted: "The income was deleted after this ran. This record shows what happened at the time.",
};

const AUDIT_ACTORS: Record<string, string> = { user: "You", system: "Valor Finis" };

const has = (table: Record<string, string>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(table, key);

export function auditLine(audit: Pick<RuleExecutionAudit, "code" | "actor">): string | null {
  if (!has(AUDIT_COPY, audit.code) || !has(AUDIT_ACTORS, audit.actor)) {
    return null;
  }

  return `${AUDIT_ACTORS[audit.actor]}: ${AUDIT_COPY[audit.code]}`;
}

// Oldest first; rows with the same or an unreadable time keep the stored order.
export function auditLines(audit: readonly RuleExecutionAudit[]): string[] {
  return audit
    .map((row, index) => ({ row, index, time: Date.parse(row.created_at) }))
    .sort((a, b) => {
      if (Number.isFinite(a.time) && Number.isFinite(b.time) && a.time !== b.time) {
        return a.time - b.time;
      }

      return a.index - b.index;
    })
    .flatMap(({ row }) => {
      const line = auditLine(row);

      return line === null ? [] : [line];
    });
}

// ------------------------------------------------------------ name lookup

// Names come from the Rules / Goals lists the app already holds. `loaded` is
// false while that list is loading or failed: then "missing" is unknown, not
// "deleted".
export type NameDirectory = { loaded: boolean; names: ReadonlyMap<string, string> };

export const UNLOADED_DIRECTORY: NameDirectory = { loaded: false, names: new Map() };

export function ruleName(directory: NameDirectory, ruleId: string): string {
  return directory.names.get(ruleId) ?? (directory.loaded ? HISTORY_COPY.ruleGone : HISTORY_COPY.ruleFallback);
}

export function goalName(directory: NameDirectory, goalId: string): string {
  return directory.names.get(goalId) ?? (directory.loaded ? HISTORY_COPY.goalGone : HISTORY_COPY.goalFallback);
}

// ------------------------------------------------------------------- card

export type HistoryGoalRow = {
  key: string;
  name: string;
  planned: string;
  applied: string;
  reservationRecorded: boolean;
};

export type HistoryCardView = {
  id: string;
  status: ExecutionStatus;
  statusLabel: string;
  heading: string;
  ranAt: string;
  decidedAt: string | null;
  explanation: string;
  reason: string | null;
  // Shown only when neither the explanation nor the reason already says it.
  nothingReserved: string | null;
  awaitingDecision: boolean;
  summaryLabel: string;
  rule: string;
  version: string;
  goals: HistoryGoalRow[];
  goalsNote: string | null;
  figuresNote: string | null;
  figures: { label: string; value: string }[];
  activity: string[];
};

const money = (amount: string, currency: string): string => `${amount} ${currency}`;

export function buildHistoryCard(
  execution: RuleExecution,
  rules: NameDirectory,
  goals: NameDirectory,
): HistoryCardView {
  const status = executionStatusInfo(execution.status);
  const reason = reasonText(execution.reason_code);
  const explanation = statusExplanation(execution.status);
  const currency = execution.source_currency;
  const heading = `Income ${money(execution.source_amount, currency)}, received ${formatDateOnly(execution.source_received_at)}`;
  const ranAt = `Ran ${formatInstant(execution.created_at)}`;
  const decidedAt = execution.decided_at === null ? null : `Decided ${formatInstant(execution.decided_at)}`;
  const stated = `${explanation} ${reason ?? ""}`;
  const nothingReserved =
    NOTHING_WRITTEN.has(execution.status) && !stated.includes(HISTORY_COPY.nothingReserved)
      ? HISTORY_COPY.nothingReserved
      : null;

  // Capacity is the Account's figures; they share the income's currency except
  // when the run was blocked for exactly that mismatch.
  const mismatch = execution.reason_code === "currency_mismatch";
  const figure = (value: string | null): string =>
    value === null ? HISTORY_COPY.notRecorded : mismatch ? value : money(value, currency);

  return {
    id: execution.id,
    status: execution.status,
    statusLabel: status.label,
    heading,
    ranAt,
    decidedAt,
    explanation,
    reason,
    nothingReserved,
    awaitingDecision: execution.status === "awaiting_confirmation",
    summaryLabel: [status.label, heading, ranAt, explanation, reason, nothingReserved]
      .filter((part): part is string => part !== null && part !== "")
      .join(". "),
    rule: ruleName(rules, execution.rule_id),
    version: `Recorded version ${execution.rule_version}`,
    goals: execution.items.map((item) => ({
      key: item.id,
      name: goalName(goals, item.goal_id),
      planned: money(item.planned_amount, currency),
      applied: item.applied_amount === null ? HISTORY_COPY.notApplied : money(item.applied_amount, currency),
      reservationRecorded: item.goal_transaction_id !== null,
    })),
    goalsNote: execution.items.length === 0 ? HISTORY_COPY.noGoals : null,
    figuresNote: mismatch ? HISTORY_COPY.currencyNote : null,
    figures: [
      { label: `${COPY.reservableLabel} then`, value: figure(execution.capacity_reservable) },
      { label: `${COPY.floorLabel} then`, value: figure(execution.capacity_floor) },
      { label: `${COPY.holdsLabel} then`, value: figure(execution.capacity_holds) },
    ],
    activity: auditLines(execution.audit),
  };
}

// The one line about the app's own last check in this session, or null.
// Only the coarse status exists (the counters are not retained), so nothing
// numeric and nothing about retries is said.
export function checkNotice(status: EvaluationStatus): string | null {
  switch (status) {
    case "incomplete":
      return HISTORY_COPY.checkIncomplete;
    case "failed":
      return HISTORY_COPY.checkFailed;
    case "not_attempted":
    case "pending":
    case "succeeded":
      return null;
    default: {
      const exhaustive: never = status;

      throw new Error(`Unhandled evaluation status: ${String(exhaustive)}`);
    }
  }
}
