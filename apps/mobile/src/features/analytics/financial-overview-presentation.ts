import { formatDateRange } from "./analytics-presentation";
import type {
  FinancialFlowFigures,
  FinancialOverviewResponse,
} from "./analytics.types";

// Presentation-only wording for the Financial Overview (VF-019C). Nothing
// here computes a financial value: every amount, Net, savings rate, count,
// and period state comes from the backend as-is; these helpers only choose
// how an already-calculated value reads as text.

// The overview's period line, from the backend's own period_state and
// YYYY-MM-DD strings (never re-derived from the device date).
export function formatOverviewPeriodNote(overview: FinancialOverviewResponse): string {
  switch (overview.period_state) {
    case "complete":
      return `Complete month · ${formatDateRange(overview.period_start, overview.period_end)}`;
    case "in_progress":
      return overview.effective_end
        ? `In progress · includes records through ${overview.effective_end}`
        : "In progress";
    case "future":
      return "This month has not started yet, so nothing is included.";
  }
}

// A trend bucket's status line, from the backend's is_complete flag.
export function formatBucketPeriodNote(isComplete: boolean, effectiveEnd: string): string {
  return isComplete ? "Complete month" : `In progress · through ${effectiveEnd}`;
}

// "26.78%", or an explanation when the backend returned null -- which it
// does exactly when there is no resolved income, so the rate is undefined
// (never shown as 0%).
export function formatSavingsRate(savingsRatePercent: string | null): string {
  return savingsRatePercent === null
    ? "Unavailable (no resolved income in this period)"
    : `${savingsRatePercent}%`;
}

// Net (Income - Expenses) with its direction spelled out, so a deficit is
// understandable without relying on color: "-150.00 EUR (deficit)". The
// direction is read from the backend's own string (its sign and whether
// it is zero), never by parsing it into a number.
export function formatNetFlow(netFlow: string, currency: string): string {
  const amount = `${netFlow} ${currency}`;

  if (/^-?0+(\.0+)?$/.test(netFlow)) {
    return `${amount} (break-even)`;
  }

  return netFlow.startsWith("-") ? `${amount} (deficit)` : `${amount} (surplus)`;
}

// "2 income records · 41 expenses" -- singularized for exactly one.
export function formatRecordCounts(incomeCount: number, expenseCount: number): string {
  const income = `${incomeCount} income ${incomeCount === 1 ? "record" : "records"}`;
  const expenses = `${expenseCount} ${expenseCount === 1 ? "expense" : "expenses"}`;

  return `${income} · ${expenses}`;
}

// Whether a period has records excluded from its totals. For a trend
// bucket this is the only completeness signal (buckets have no
// data_status); the overview has the backend's own data_status.
export function hasUnresolvedRecords(figures: FinancialFlowFigures): boolean {
  return figures.unresolved_income_count > 0 || figures.unresolved_expense_count > 0;
}

// Whether a period has no records at all, resolved or not.
export function hasNoRecords(figures: FinancialFlowFigures): boolean {
  return (
    figures.income_count === 0 &&
    figures.expense_count === 0 &&
    !hasUnresolvedRecords(figures)
  );
}

// Explains which records are missing from the totals, e.g. "1 income
// record and 2 expenses could not be counted in EUR and are not included
// in these totals."
export function formatIncompleteNotice(
  figures: FinancialFlowFigures,
  currency: string,
): string {
  const parts: string[] = [];

  if (figures.unresolved_income_count > 0) {
    const count = figures.unresolved_income_count;
    parts.push(`${count} income ${count === 1 ? "record" : "records"}`);
  }

  if (figures.unresolved_expense_count > 0) {
    const count = figures.unresolved_expense_count;
    parts.push(`${count} ${count === 1 ? "expense" : "expenses"}`);
  }

  const excludedCount =
    figures.unresolved_income_count + figures.unresolved_expense_count;

  return (
    `${parts.join(" and ")} could not be counted in ${currency} and ` +
    `${excludedCount === 1 ? "is" : "are"} not included in these totals.`
  );
}
