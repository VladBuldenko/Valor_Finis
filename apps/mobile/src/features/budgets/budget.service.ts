import { apiRequest } from "../../api/api-client";

import type { Budget } from "./budget.types";

/**
 * Returns all budgets that belong to the authenticated user.
 *
 * Budget spending progress (spent/remaining/exceeded) is not part of this
 * response -- it comes from the analytics budget-status endpoint, which
 * already has its own service function in analytics.service.ts and is
 * reused directly by screens rather than duplicated here.
 */
export async function getBudgets(): Promise<Budget[]> {
  return apiRequest<Budget[]>("/api/v1/budgets");
}
