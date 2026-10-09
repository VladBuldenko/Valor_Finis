import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the server-state caches affected by a successful Goal
 * transaction create (HTTP 201 and an idempotent 200 replay alike).
 *
 * Always: the Goal list (current/tracked/linked amounts and allocations),
 * this Goal's transaction history, and Goal Progress analytics (which is
 * based on current_amount).
 *
 * A linked reservation / release additionally refreshes the Account list,
 * because the Account's reserved_amount and reservable_amount changed.
 *
 * Deliberately NOT invalidated: Account transaction history (a reservation
 * writes no AccountTransaction and never changes current_balance), income,
 * expenses, transfers, budgets, Financial Overview and the other analytics.
 * New balances always come from a refetch, never from a local calculation.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 * - goalId: the Goal the transaction belongs to.
 * - isLinked: true when the request carried an account_id.
 */
export function invalidateGoalTransactionQueries(
  queryClient: QueryClient,
  userId: string | undefined,
  goalId: string,
  isLinked: boolean,
): Promise<unknown> {
  const invalidations: Promise<unknown>[] = [
    queryClient.invalidateQueries({ queryKey: ["goals", userId] }),
    queryClient.invalidateQueries({
      queryKey: ["goals", "transactions", userId, goalId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "goal-progress", userId],
    }),
  ];

  if (isLinked) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["accounts", userId] }),
    );
  }

  return Promise.all(invalidations);
}
