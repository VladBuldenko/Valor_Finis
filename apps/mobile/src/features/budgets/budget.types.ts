export type BudgetPeriod = "weekly" | "monthly" | "yearly";

export type Budget = {
  id: string;
  user_id: string;
  category_id: string | null;
  name: string;
  limit_amount: string;
  currency: string;
  period: BudgetPeriod;
  start_date: string;
  end_date: string | null;
  created_at: string;
  updated_at: string;
};

// Mirrors backend BudgetCreate (services/api/app/modules/budgets/budget_schemas.py).
// user_id is intentionally omitted -- it is derived from authentication on
// the server and must never be sent from the client. currency and period
// are optional because the backend defaults them ("EUR" / "monthly") when
// omitted.
export type BudgetCreateInput = {
  category_id?: string | null;
  name: string;
  limit_amount: string;
  currency?: string;
  period?: BudgetPeriod;
  start_date: string;
  end_date?: string | null;
};
