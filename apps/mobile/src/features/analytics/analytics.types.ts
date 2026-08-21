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