import { apiRequest } from "../../api/api-client";

import type {
  Expense,
  ExpenseCreateInput,
  ExpenseUpdateInput,
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

/**
 * Updates an expense owned by the authenticated user.
 */
export async function updateExpense(
  expenseId: string,
  expenseData: ExpenseUpdateInput,
): Promise<Expense> {
  return apiRequest<Expense>(
    `/api/v1/expenses/${expenseId}`,
    {
      method: "PATCH",
      body: JSON.stringify(expenseData),
    },
  );
}

/**
 * Deletes an expense owned by the authenticated user.
 */
export async function deleteExpense(
  expenseId: string,
): Promise<void> {
  return apiRequest<void>(
    `/api/v1/expenses/${expenseId}`,
    {
      method: "DELETE",
    },
  );
}