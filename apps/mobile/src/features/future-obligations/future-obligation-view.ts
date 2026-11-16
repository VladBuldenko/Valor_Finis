// VF-GOALS-PLANNING-002C1: wording for "Upcoming bills". Pure and Node-testable.
// Every amount, count and date here is the backend's own answer from
// GET /future-obligations and /future-obligations/upcoming: nothing is added,
// rounded or compared as money on the device (a currency total is shown exactly as
// the backend sent it, and different currencies are never combined).
//
// A bill is a forecast input the user typed in. The copy never says a bill is
// paid, reserved or recorded as an expense, never compares the bills with past
// spending or income, and never says whether the user can cover them.
import type {
  FutureObligation,
  ObligationSchedule,
  UpcomingMonth,
  UpcomingObligations,
} from "./future-obligation.types.ts";

export const BILLS_TITLE = "Upcoming bills";

export const BILLS_INTRO =
  "Add the bills you know are coming, such as rent or an insurance renewal, to see what falls due over the next 12 months.";

// Said wherever bills are created or listed: what adding a bill does NOT do.
export const BILLS_NOT_PAID =
  "Adding a bill does not pay it, set money aside or add an expense. It is only a reminder of what you expect to owe.";

// What the numbers are, and are not.
export const BILLS_SCOPE =
  "These are only the bills you enter. They are not found from your past spending, and they are not compared with it, so this does not say whether you can cover them.";

// Bills and Goal contributions are different things and are never combined.
export const BILLS_SEPARATE_FROM_GOALS =
  "Bills are shown separately from your Goal contributions. The two are not added together.";

export const BILLS_EMPTY = "No bills yet. Add one to see what is coming up.";
export const BILLS_ARCHIVED_EMPTY = "No archived bills.";

export const FORM_NOT_PAID = "Saving a bill does not pay it, set money aside or add an expense.";

const money = (amount: string, currency: string): string => `${amount} ${currency}`;

export function billCount(count: number): string {
  return `${count} bill${count === 1 ? "" : "s"}`;
}

export function scheduleLabel(schedule: ObligationSchedule): string {
  return schedule === "one_time" ? "One-time" : "Monthly";
}

export type BillRow = { label: string; value: string };

// The lines of one bill on the list: its amount, when it is next due and when a
// monthly bill ends.
export function obligationLines(obligation: FutureObligation): string[] {
  const lines = [
    `${scheduleLabel(obligation.schedule)}: ${money(obligation.amount, obligation.currency)}${obligation.schedule === "monthly" ? " each month" : ""}`,
  ];

  if (obligation.status === "archived") {
    lines.push("Archived. It does not appear in upcoming bills.");
  } else if (obligation.next_due_date !== null) {
    lines.push(`Next due: ${obligation.next_due_date}`);
  } else {
    lines.push("No more due dates.");
  }

  if (obligation.schedule === "monthly") {
    lines.push(obligation.final_due_date !== null ? `Last due date: ${obligation.final_due_date}` : "No end date");
  }

  if (obligation.description !== null) {
    lines.push(obligation.description);
  }

  return lines;
}

// The current month: the first month of the window.
function thisMonth(upcoming: UpcomingObligations): UpcomingMonth | null {
  return upcoming.months[0] ?? null;
}

// The currency totals of a month or window, each in its own currency, as the
// backend sent them. The separator is not a plus sign: they are not added.
function currencyTotals(totals: { currency: string; total: string }[]): string {
  return totals.map((entry) => money(entry.total, entry.currency)).join("; ");
}

// The headline for the rest of this month, in the base currency. null when the
// backend sent no months.
export function thisMonthHeadline(upcoming: UpcomingObligations): { label: string; amount: string } | null {
  const month = thisMonth(upcoming);

  if (month === null) {
    return null;
  }

  return {
    label: "Bills due for the rest of this month",
    amount: money(month.base_currency_total, upcoming.base_currency),
  };
}

// The sentences under the headline: how many bills fall due, anything in another
// currency, and the 12-month total.
export function summaryLines(upcoming: UpcomingObligations): string[] {
  const month = thisMonth(upcoming);
  const lines: string[] = [];

  if (month === null || month.occurrence_count === 0) {
    lines.push("No bills fall due for the rest of this month.");
  } else {
    lines.push(`${billCount(month.occurrence_count)} due between today and the end of the month.`);
  }

  if (upcoming.excluded_currencies.length > 0) {
    lines.push(
      `Bills in ${upcoming.excluded_currencies.join(", ")} are listed separately and are not added to the ${upcoming.base_currency} totals.`,
    );
  }

  if (upcoming.totals_by_currency.length > 0) {
    lines.push(`Next ${upcoming.horizon_months} months: ${currencyTotals(upcoming.totals_by_currency)}`);
  }

  return lines;
}

export type MonthGroup = {
  label: string;
  value: string;
  // One line per bill due in the month, in the backend's order.
  items: BillRow[];
};

function monthValue(month: UpcomingMonth): string {
  if (month.occurrence_count === 0) {
    return "nothing due";
  }

  return `${currencyTotals(month.totals_by_currency)} (${billCount(month.occurrence_count)})`;
}

// One group per month of the window. Consecutive months with nothing due are shown
// as one range, so a short list of bills does not leave a long run of identical
// rows; every month of the window is still covered.
export function monthGroups(upcoming: UpcomingObligations): MonthGroup[] {
  const groups: MonthGroup[] = [];
  let emptyRun: string[] = [];

  const flushEmptyRun = () => {
    if (emptyRun.length > 0) {
      groups.push({
        label: emptyRun.length === 1 ? emptyRun[0] : `${emptyRun[0]} to ${emptyRun[emptyRun.length - 1]}`,
        value: "nothing due",
        items: [],
      });
      emptyRun = [];
    }
  };

  for (const month of upcoming.months) {
    const label = month.period_start.slice(0, 7);

    if (month.occurrence_count === 0) {
      emptyRun.push(label);
      continue;
    }

    flushEmptyRun();
    groups.push({
      label,
      value: monthValue(month),
      items: month.occurrences.map((occurrence) => ({
        label: `${occurrence.due_date} · ${occurrence.name}`,
        value: money(occurrence.amount, occurrence.currency),
      })),
    });
  }

  flushEmptyRun();

  return groups;
}

// The compact summary for the Goals screen: this month in the base currency, how
// many bills, and the 12-month total. Kept apart from the Goal plan amounts.
export function goalsCardLines(upcoming: UpcomingObligations): string[] {
  const month = thisMonth(upcoming);
  const lines: string[] = [];

  lines.push(
    month === null || month.occurrence_count === 0
      ? "No bills fall due for the rest of this month."
      : `${billCount(month.occurrence_count)} due between today and the end of the month.`,
  );

  if (upcoming.is_base_total_complete) {
    lines.push(`Next ${upcoming.horizon_months} months: ${money(upcoming.base_currency_window_total, upcoming.base_currency)}`);
  } else {
    lines.push(
      `Next ${upcoming.horizon_months} months: ${currencyTotals(upcoming.totals_by_currency)}. Bills in different currencies are not added together.`,
    );
  }

  return lines;
}

// True when there is nothing to summarize: no bill falls due in the whole window.
export function hasNoUpcomingBills(upcoming: UpcomingObligations): boolean {
  return upcoming.totals_by_currency.length === 0;
}

export function archiveConfirmation(name: string): { title: string; message: string } {
  return {
    title: "Archive this bill?",
    message: `"${name}" will no longer appear in upcoming bills. You can restore it later. Nothing is paid or deleted.`,
  };
}
