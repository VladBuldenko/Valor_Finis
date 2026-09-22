import { apiRequest } from "../../api/api-client";

import type {
  Goal,
  GoalCreateInput,
  GoalTransaction,
  GoalTransactionCreateInput,
  GoalUpdateInput,
} from "./goal.types";

/**
 * Returns all financial goals that belong to the authenticated user.
 *
 * Goal progress (remaining amount / progress percent) is not part of this
 * response -- it comes from the analytics goal-progress endpoint, which
 * already has its own service function in analytics.service.ts and is
 * reused directly by screens rather than duplicated here (mirrors how
 * BudgetStatusItem/getBudgetStatus() relates to Budget/getBudgets()).
 */
export async function getGoals(): Promise<Goal[]> {
  return apiRequest<Goal[]>("/api/v1/goals");
}

/**
 * Creates a goal for the authenticated user.
 */
export async function createGoal(
  goalData: GoalCreateInput,
): Promise<Goal> {
  return apiRequest<Goal>("/api/v1/goals", {
    method: "POST",
    body: JSON.stringify(goalData),
  });
}

/**
 * Updates a goal owned by the authenticated user.
 * Only the fields present in goalData are changed -- callers are
 * responsible for omitting fields that did not change (see
 * GoalUpdateInput / the backend's exclude_unset PATCH semantics).
 */
export async function updateGoal(
  goalId: string,
  goalData: GoalUpdateInput,
): Promise<Goal> {
  return apiRequest<Goal>(`/api/v1/goals/${goalId}`, {
    method: "PATCH",
    body: JSON.stringify(goalData),
  });
}

/**
 * Deletes a goal owned by the authenticated user.
 * The backend returns 204 No Content on success, which apiRequest already
 * handles centrally (it returns undefined without parsing a body).
 */
export async function deleteGoal(goalId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/goals/${goalId}`, {
    method: "DELETE",
  });
}

/**
 * Returns a goal's full transaction history, newest first (the backend's
 * own ordering -- never re-sorted client-side). Includes migration-created
 * opening_balance entries alongside contribution/withdrawal entries.
 */
export async function getGoalTransactions(
  goalId: string,
): Promise<GoalTransaction[]> {
  return apiRequest<GoalTransaction[]>(
    `/api/v1/goals/${goalId}/transactions`,
  );
}

/**
 * Creates a contribution or withdrawal transaction for a goal owned by the
 * authenticated user. The backend is the sole authority on insufficient-
 * funds validation (a withdrawal larger than the current ledger balance
 * fails with 409) -- this never pre-validates the amount against the
 * goal's balance client-side.
 */
export async function createGoalTransaction(
  goalId: string,
  transactionData: GoalTransactionCreateInput,
): Promise<GoalTransaction> {
  return apiRequest<GoalTransaction>(
    `/api/v1/goals/${goalId}/transactions`,
    {
      method: "POST",
      body: JSON.stringify(transactionData),
    },
  );
}
