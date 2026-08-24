import { apiRequest } from "../../api/api-client";

import type {
  Expense,
  ExpenseCreateInput,
} from "./expense.types";

/**
 * Returns expenses that belong to the authenticated user.
 */
export async function getExpenses(): Promise<Expense[]> {
  return apiRequest<Expense[]>("/api/v1/expenses");
}

/**
 * Creates an expense for the authenticated user.
 */
export async function createExpense(
  expenseData: ExpenseCreateInput,
): Promise<Expense> {
  return apiRequest<Expense>(
    "/api/v1/expenses",
    {
      method: "POST",
      body: JSON.stringify(expenseData),
    },
  );
}