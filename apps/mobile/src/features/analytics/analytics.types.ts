export type MonthlySummary = {
    total_spent: string;
    expenses_count: number;
  };
  
  export type CategorySummaryItem = {
    category_id: string | null;
    category_name: string;
    total_spent: string;
    expenses_count: number;
  };
  
  export type BudgetStatusItem = {
    budget_id: string;
    budget_name: string;
    category_id: string | null;
    category_name: string;
    limit_amount: string;
    spent: string;
    remaining: string;
    exceeded_amount: string;
    is_exceeded: boolean;
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