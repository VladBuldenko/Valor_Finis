import type {
  SpendingForecastStatus,
  SpendingTrendDirection,
  SpendingTrendPeriod,
} from "./analytics.types";

// Presentation-only label maps and string formatters for Analytics v2
// (VF-015E). These never derive meaning -- the backend remains the sole
// authority on every calculated value and every literal; this file only
// decides how an already-backend-computed value reads as text.

const PERIOD_LABELS: Record<SpendingTrendPeriod, string> = {
  day: "Day",
  week: "Week",
  month: "Month",
};

export function formatPeriodLabel(period: SpendingTrendPeriod): string {
  return PERIOD_LABELS[period];
}

const DIRECTION_LABELS: Record<SpendingTrendDirection, string> = {
  up: "Up",
  down: "Down",
  unchanged: "Unchanged",
};

export function formatDirectionLabel(direction: SpendingTrendDirection): string {
  return DIRECTION_LABELS[direction];
}

const FORECAST_STATUS_LABELS: Record<SpendingForecastStatus, string> = {
  available: "Current spending pace",
  incomplete_data: "Forecast unavailable",
};

export function formatForecastStatusLabel(status: SpendingForecastStatus): string {
  return FORECAST_STATUS_LABELS[status];
}

// Renders a backend Decimal-string amount with its currency code, e.g.
// "184.73 EUR". Never parses the amount through Number() -- this is pure
// string concatenation, so it can never introduce float drift into a
// value the backend already computed exactly.
export function formatAmount(amount: string, currency: string): string {
  return `${amount} ${currency}`;
}

// Renders a backend Decimal-string percentage, e.g. "12.50%". Displayed
// exactly as the backend returned it -- never recomputed or clamped here.
export function formatPercent(value: string): string {
  return `${value}%`;
}

// "1 expense"/"2 expenses" -- singularize only for exactly one.
export function formatExpenseCount(count: number): string {
  return `${count} ${count === 1 ? "expense" : "expenses"}`;
}

// "2 unresolved expenses are not included in this total." Shared wording
// for the same notice across buckets, categories, and the forecast card.
export function formatUnresolvedNotice(count: number): string {
  return `${count} unresolved ${count === 1 ? "expense is" : "expenses are"} not included in this total.`;
}

// A calendar bucket's date range, presented directly from the backend's
// own YYYY-MM-DD strings -- deliberately never constructs a JS Date from
// a date-only string, which risks a UTC/local timezone shift landing on
// the wrong calendar day.
export function formatDateRange(start: string, end: string): string {
  return start === end ? start : `${start} – ${end}`;
}
