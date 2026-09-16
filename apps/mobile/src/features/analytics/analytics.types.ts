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