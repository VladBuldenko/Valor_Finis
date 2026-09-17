// total_spent is base-currency spending (VF-014B5D): summed from each
// resolved Expense's backend-persisted base_amount, never the original
// mixed-currency amount, and never recomputed client-side.
export type MonthlySummary = {
    total_spent: string;
    expenses_count: number;
    base_currency: string;
    unresolved_expenses_count: number;
  };

  // total_spent is base-currency spending (VF-014B5D) - see MonthlySummary above.
  export type CategorySummaryItem = {
    category_id: string | null;
    category_name: string;
    total_spent: string;
    expenses_count: number;
    base_currency: string;
    unresolved_expenses_count: number;
  };
  
  // Mirrors backend BudgetStatusItem (services/api/app/modules/analytics/analytics_schemas.py, VF-014B3/B4).
  // All Decimal/date fields stay strings -- the backend remains the sole
  // authority on every calculated value here (period boundaries, spent,
  // utilization, days, allowance, projection, risk). Mobile must never
  // recompute any of these from other fields.
  export type BudgetPeriod = "weekly" | "monthly" | "yearly";
  export type BudgetPeriodState = "not_started" | "active" | "ended";
  export type BudgetRiskStatus = "healthy" | "watch" | "at_risk" | "exceeded";

  export type BudgetStatusItem = {
    budget_id: string;
    budget_name: string;
    category_id: string | null;
    category_name: string;

    period: BudgetPeriod;
    period_start: string;
    period_end: string;

    effective_start: string;
    effective_end: string;
    period_state: BudgetPeriodState;
    is_partial_period: boolean;

    limit_amount: string;
    spent: string;
    remaining: string;
    exceeded_amount: string;
    utilization_percent: string;
    is_exceeded: boolean;

    days_in_period: number;
    days_elapsed: number;
    days_remaining: number;

    average_daily_spending: string;
    daily_spending_allowance: string;

    // Null exactly when there is no observed pace yet (not_started). For
    // an ended budget this is the actual final spend, not a live forecast
    // -- see budget-status-presentation.ts.
    projected_spending: string | null;
    // Both null exactly when projected_spending is null.
    projected_surplus: string | null;
    projected_deficit: string | null;

    risk_status: BudgetRiskStatus;
  };

  // Mirrors backend GoalProgressItem (services/api/app/modules/analytics/analytics_schemas.py).
  // goal_id is the join key back to Goal.id (see ../goals/goal.types.ts).
  // remaining_amount and progress_percent are backend-computed -- never
  // recompute them client-side. Deliberately has no currency field (the
  // backend schema does not define one); read currency from the joined
  // Goal object instead of hardcoding or inventing one here.
  export type GoalProgressItem = {
    goal_id: string;
    name: string;
    target_amount: string;
    current_amount: string;
    remaining_amount: string;
    progress_percent: string;
    status: string;
    target_date: string | null;
  };

  // Mirrors backend Spending Trend / Category Trend / Spending Forecast
  // (VF-015B/C/D, services/api/app/modules/analytics/analytics_schemas.py).
  // Every Decimal/date field stays a string -- the backend remains the sole
  // authority on every calculated value here (totals, FX resolution,
  // absolute/percent change, direction, forecast). Mobile must never
  // recompute any of these; it only chooses which values to render.
  export type SpendingTrendPeriod = "day" | "week" | "month";
  export type SpendingTrendDirection = "up" | "down" | "unchanged";

  // A single calendar bucket. Always exactly the requested `count` buckets
  // are returned per series, including buckets with no Expenses at all
  // (total_spent "0.00") -- the backend deliberately never omits an empty
  // period, so mobile must never reconstruct or filter out missing dates.
  export type SpendingTrendBucket = {
    period_start: string;
    period_end: string;
    effective_end: string;
    is_complete: boolean;
    total_spent: string;
    expenses_count: number;
    unresolved_expenses_count: number;
  };

  // Comparison between the two most recent COMPLETE buckets in a series.
  // percent_change is null when the previous period's total was zero --
  // never render that as "0%", it is a mathematically undefined value, not
  // a real zero. direction is backend-computed; never derive it from
  // absolute_change or percent_change client-side.
  export type PeriodOverPeriodComparison = {
    current_period_start: string;
    current_period_end: string;
    previous_period_start: string;
    previous_period_end: string;
    current_total_spent: string;
    previous_total_spent: string;
    absolute_change: string;
    percent_change: string | null;
    direction: SpendingTrendDirection;
  };

  export type SpendingTrendResponse = {
    base_currency: string;
    period: SpendingTrendPeriod;
    count: number;
    as_of: string;
    buckets: SpendingTrendBucket[];
    period_over_period: PeriodOverPeriodComparison | null;
  };

  // category_id is null for Uncategorized -- render category_name exactly
  // as returned ("Uncategorized" is the backend's own fallback label, not
  // a client-invented one). Categories are already in the backend's
  // deterministic order; never re-sort or filter by total_spent client-side.
  export type CategoryTrendItem = {
    category_id: string | null;
    category_name: string;
    buckets: SpendingTrendBucket[];
    period_over_period: PeriodOverPeriodComparison | null;
  };

  export type CategoryTrendResponse = {
    base_currency: string;
    period: SpendingTrendPeriod;
    count: number;
    as_of: string;
    categories: CategoryTrendItem[];
  };

  // Deterministic current-month spending pace projection (VF-015D). This
  // is CURRENT-MONTH SPENDING PACE PROJECTION only -- never a cash-flow,
  // income, savings, or net-worth forecast, and there is no history/model
  // selection: method is always "linear_run_rate" today.
  export type SpendingForecastMethod = "linear_run_rate";
  export type SpendingForecastStatus = "available" | "incomplete_data";

  // When forecast_status is "incomplete_data", average_daily_spending and
  // projected_spending are both null -- the backend never projects from
  // known-incomplete monetary data. spent_to_date/expenses_count/
  // unresolved_expenses_count stay populated regardless of status; never
  // hide spent_to_date just because the forecast itself is unavailable,
  // and never substitute "0.00" for a null forecast figure.
  export type SpendingForecastResponse = {
    base_currency: string;
    method: SpendingForecastMethod;
    forecast_status: SpendingForecastStatus;
    period_start: string;
    period_end: string;
    as_of: string;
    days_in_month: number;
    days_elapsed: number;
    spent_to_date: string;
    expenses_count: number;
    unresolved_expenses_count: number;
    average_daily_spending: string | null;
    projected_spending: string | null;
  };