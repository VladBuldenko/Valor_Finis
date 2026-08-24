export type Expense = {
    id: string;
    user_id: string;
    category_id: string | null;
    title: string;
    amount: string;
    currency: string;
    expense_date: string;
    description: string | null;
    source: string;
    created_at: string;
    updated_at: string;
  };

  export type ExpenseCreateInput = {
    category_id?: string | null;
    title: string;
    amount: string;
    currency?: string;
    expense_date: string;
    description?: string | null;
    source?: string;
  };