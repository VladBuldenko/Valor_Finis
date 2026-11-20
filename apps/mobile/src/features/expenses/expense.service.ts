import { apiRequest } from "../../api/api-client";

import { pagedPath, type Page } from "../../lib/paged-list";
import type {
  Expense,
  ExpenseCreateInput,
  ExpenseUpdateInput,
} from "./expense.types";

/**
 * Returns ONE page of the authenticated user's expenses, newest first, with
 * the user's total number of expenses. The page is requested explicitly
 * (limit/offset); a request without them would return the complete bare list.
 */
export async function getExpensesPage(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<Page<Expense>> {
  return apiRequest<Page<Expense>>(
    pagedPath("/api/v1/expenses", limit, offset),
    { signal },
  );
}

/**
 * Returns one expense of the authenticated user. This is how the detail/edit
 * screen opens an expense that is not on any loaded page; an id that does not
 * exist and an id of another user are both a 404.
 */
export async function getExpense(
  expenseId: string,
  signal?: AbortSignal,
): Promise<Expense> {
  return apiRequest<Expense>(`/api/v1/expenses/${expenseId}`, { signal });
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