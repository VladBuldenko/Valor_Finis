import { apiRequest } from "../../api/api-client";

import type { Expense } from "./expense.types";

/**
 * Returns expenses that belong to the authenticated user.
 */
export async function getExpenses(): Promise<Expense[]> {
  return apiRequest<Expense[]>("/api/v1/expenses");
}