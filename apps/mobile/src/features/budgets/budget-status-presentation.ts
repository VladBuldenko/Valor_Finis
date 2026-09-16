import type {
  BudgetPeriod,
  BudgetPeriodState,
  BudgetRiskStatus,
} from "../analytics/analytics.types";

// Presentation-only label maps for backend literals (VF-014B6). These
// never derive meaning -- the backend remains the sole authority on which
// literal applies to a given Budget Status item; this only decides how
// each literal reads as text. Reused by both budgets-screen.tsx (full
// detail) and dashboard-screen.tsx (compact) so the wording never drifts
// between the two screens.

const PERIOD_LABELS: Record<BudgetPeriod, string> = {
  weekly: "Weekly",
  monthly: "Monthly",
  yearly: "Yearly",
};

export function formatPeriodLabel(period: BudgetPeriod): string {
  return PERIOD_LABELS[period];
}

const PERIOD_STATE_LABELS: Record<BudgetPeriodState, string> = {
  not_started: "Not started",
  active: "Active",
  ended: "Ended",
};

export function formatPeriodStateLabel(state: BudgetPeriodState): string {
  return PERIOD_STATE_LABELS[state];
}

const RISK_LABELS: Record<BudgetRiskStatus, string> = {
  healthy: "On track",
  watch: "Watch",
  at_risk: "At risk",
  exceeded: "Exceeded",
};

export function formatRiskLabel(risk: BudgetRiskStatus): string {
  return RISK_LABELS[risk];
}

// Renders a backend Decimal-string amount with its currency code, e.g.
// "184.73 EUR". Never parses the amount through Number() -- this is pure
// string concatenation, so it can never introduce float drift into a
// value the backend already computed exactly.
export function formatAmount(amount: string, currency: string): string {
  return `${amount} ${currency}`;
}

// Renders a backend Decimal-string percentage, e.g. "78.42%". The value
// is displayed exactly as the backend returned it, including above 100%
// for an exceeded budget -- never clamped or recomputed here.
export function formatPercent(value: string): string {
  return `${value}%`;
}

// "1 expense"/"2 expenses" -- singularize only for exactly one. Shared
// wording for the B5D unresolved-legacy-expense notices (Dashboard) and
// any future spot that needs the same count phrasing.
export function formatUnresolvedNotice(count: number): string {
  return `${count} legacy ${count === 1 ? "expense is" : "expenses are"} not included in this total.`;
}
