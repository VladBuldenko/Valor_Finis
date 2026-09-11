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

// Mirrors backend BudgetUpdate (services/api/app/modules/budgets/budget_schemas.py).
// Every field is optional -- an omitted field is left unchanged by the
// backend (it uses `model_dump(exclude_unset=True)`). category_id and
// end_date are the only fields where an explicit null is meaningful (they
// clear the category / end date); the backend rejects an explicit null for
// name, limit_amount, currency, period, and start_date, so those are typed
// as plain optional values rather than nullable. user_id is intentionally
// omitted -- it is derived from authentication on the server.
export type BudgetUpdateInput = {
  category_id?: string | null;
  name?: string;
  limit_amount?: string;
  currency?: string;
  period?: BudgetPeriod;
  start_date?: string;
  end_date?: string | null;
};
