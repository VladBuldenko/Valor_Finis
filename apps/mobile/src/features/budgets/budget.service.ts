import { apiRequest } from "../../api/api-client";

import type {
  Budget,
  BudgetCreateInput,
  BudgetUpdateInput,
} from "./budget.types";

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

/**
 * Creates a budget for the authenticated user.
 */
export async function createBudget(
  budgetData: BudgetCreateInput,
): Promise<Budget> {
  return apiRequest<Budget>("/api/v1/budgets", {
    method: "POST",
    body: JSON.stringify(budgetData),
  });
}

/**
 * Updates a budget owned by the authenticated user.
 * Only the fields present in budgetData are changed -- callers are
 * responsible for omitting fields that did not change (see
 * BudgetUpdateInput / the backend's exclude_unset PATCH semantics).
 */
export async function updateBudget(
  budgetId: string,
  budgetData: BudgetUpdateInput,
): Promise<Budget> {
  return apiRequest<Budget>(`/api/v1/budgets/${budgetId}`, {
    method: "PATCH",
    body: JSON.stringify(budgetData),
  });
}
