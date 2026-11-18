// VF-GOALS-PLANNING-002C2: wording and ordering for linking an expense to a bill date.
// Pure and Node-testable. Every amount, date and count is the backend's own answer:
// nothing is added, rounded or compared as money on the device.
//
// A link means "this recorded expense corresponds to this bill date". The copy never
// says a bill is paid, confirmed or verified, never calls a date without a link
// unpaid, overdue or owed, and never promises that anything moves or changes.
import type {
  CandidateExpense,
  OccurrenceCandidates,
  ReconciliationOccurrence,
  ReconciliationOverview,
} from "./future-obligation-link.types.ts";

export const LINKS_TITLE = "Linked expenses";

export const LINKS_INTRO =
  "Link an expense you already recorded to a date of one of your bills. You choose the expense yourself; nothing is matched automatically.";

// What a link is, and is not. Shown on the list, the date and the picker.
export const LINK_MEANING =
  "A link only records that an expense goes with a bill date. It does not pay the bill, move money, change an account balance or add an expense, and nothing is checked with your bank.";

export const LINKS_EMPTY = "No bill dates to show yet. Add a bill to see its dates here.";

export const STATUS_LINKED = "Expense linked";
export const STATUS_NOT_LINKED = "No expense linked";

// Said once a date has no link, so it is never read as a debt.
export const NOT_LINKED_NOTE =
  "No expense is linked to this date. That does not mean it is unpaid; you may just not have linked it.";

export const PICKER_TITLE = "Choose an expense to link";

export const PICKER_RULES =
  "Only an expense in the same currency with exactly the same amount can be linked. Amounts are never converted.";

// How many coming bill dates are shown before "Show more" (the list reaches 12 months ahead).
export const UPCOMING_PREVIEW_COUNT = 12;

const money = (amount: string, currency: string): string => `${amount} ${currency}`;

export function occurrenceTitle(occurrence: ReconciliationOccurrence): string {
  return `${occurrence.due_date} · ${occurrence.name}`;
}

export function occurrenceAmount(occurrence: Pick<ReconciliationOccurrence, "amount" | "currency">): string {
  return money(occurrence.amount, occurrence.currency);
}

export function statusLabel(occurrence: ReconciliationOccurrence): string {
  return occurrence.linked_expense !== null ? STATUS_LINKED : STATUS_NOT_LINKED;
}

// The row on the list: what the date is and whether an expense is linked.
export function occurrenceRowLines(occurrence: ReconciliationOccurrence): string[] {
  const lines = [occurrenceAmount(occurrence), statusLabel(occurrence)];

  if (occurrence.linked_expense !== null) {
    lines.push(`${occurrence.linked_expense.title} · ${occurrence.linked_expense.expense_date}`);
  }

  if (occurrence.obligation_status === "archived") {
    lines.push("This bill is archived.");
  }

  return lines;
}

export function occurrenceAccessibilityLabel(occurrence: ReconciliationOccurrence): string {
  return `${occurrenceTitle(occurrence)}, ${occurrenceAmount(occurrence)}, ${statusLabel(occurrence)}`;
}

export type OccurrenceSections = {
  // Dates before today, the most recent first.
  recent: ReconciliationOccurrence[];
  // Today and later, the soonest first. `hidden` is how many are left out of `upcoming`.
  upcoming: ReconciliationOccurrence[];
  hiddenUpcoming: number;
};

// Splits the backend's overview (already ordered by due date) into the recent
// dates and the coming ones. Only the order of the list is used: the backend
// said which dates are past (is_past), so no date is compared here.
export function occurrenceSections(
  overview: ReconciliationOverview,
  showAllUpcoming: boolean,
): OccurrenceSections {
  const recent = overview.occurrences.filter((occurrence) => occurrence.is_past).reverse();
  const upcomingAll = overview.occurrences.filter((occurrence) => !occurrence.is_past);
  const upcoming = showAllUpcoming ? upcomingAll : upcomingAll.slice(0, UPCOMING_PREVIEW_COUNT);

  return { recent, upcoming, hiddenUpcoming: upcomingAll.length - upcoming.length };
}

// The occurrence a route's (bill id, due date) points to, or null when it is not
// (or is no longer) in the window.
export function findOccurrence(
  overview: ReconciliationOverview,
  obligationId: string,
  dueDate: string,
): ReconciliationOccurrence | null {
  return (
    overview.occurrences.find(
      (occurrence) => occurrence.obligation_id === obligationId && occurrence.due_date === dueDate,
    ) ?? null
  );
}

export function candidateLines(candidate: CandidateExpense): string[] {
  return [candidate.title, `${candidate.expense_date} · ${money(candidate.amount, candidate.currency)}`];
}

const expenses = (count: number): string => `${count} expense${count === 1 ? "" : "s"}`;

// Why other expenses are not offered, so a missing one is understandable. Empty
// when nothing is excluded.
export function exclusionLines(candidates: OccurrenceCandidates): string[] {
  const { excluded } = candidates;
  const lines: string[] = [];

  if (excluded.different_amount > 0) {
    lines.push(
      `${expenses(excluded.different_amount)} in ${candidates.currency} ${excluded.different_amount === 1 ? "has" : "have"} a different amount than ${money(candidates.amount, candidates.currency)}, so cannot be linked.`,
    );
  }

  if (excluded.different_currency > 0) {
    lines.push(
      `${expenses(excluded.different_currency)} ${excluded.different_currency === 1 ? "is" : "are"} not in ${candidates.currency} and cannot be linked. Nothing is converted.`,
    );
  }

  if (excluded.already_linked > 0) {
    lines.push(
      `${expenses(excluded.already_linked)} with this amount ${excluded.already_linked === 1 ? "is" : "are"} already linked to another bill date.`,
    );
  }

  if (excluded.dated_in_future > 0) {
    lines.push(
      `${expenses(excluded.dated_in_future)} with this amount ${excluded.dated_in_future === 1 ? "is" : "are"} dated after today and cannot be linked yet.`,
    );
  }

  return lines;
}

export function noCandidatesMessage(candidates: Pick<OccurrenceCandidates, "amount" | "currency">): string {
  return `No recorded expense of exactly ${money(candidates.amount, candidates.currency)} can be linked to this date yet. Record the expense first, or correct its amount in Expenses.`;
}

export function linkConfirmation(
  occurrence: ReconciliationOccurrence,
  candidate: CandidateExpense,
): { title: string; message: string } {
  return {
    title: "Link this expense?",
    message: `"${candidate.title}" (${candidate.expense_date}, ${money(candidate.amount, candidate.currency)}) will be linked to ${occurrence.name} due ${occurrence.due_date}. This only records that they go together. It does not pay anything or change any balance.`,
  };
}

export function unlinkConfirmation(occurrence: ReconciliationOccurrence): { title: string; message: string } {
  const title = occurrence.linked_expense?.title ?? "the expense";

  return {
    title: "Remove this link?",
    message: `"${title}" will no longer be linked to ${occurrence.name} due ${occurrence.due_date}. The expense itself is not changed or deleted.`,
  };
}

// What the user can do when the date they opened is gone (the bill was edited or
// archived, or the window moved on).
export const OCCURRENCE_GONE =
  "This bill date is no longer on your schedule. Go back to see your current bill dates.";
