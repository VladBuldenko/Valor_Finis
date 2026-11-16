import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the server-state caches affected by a successful future
 * obligation create, update or archive (including an idempotent 200 replay).
 *
 * Everything lives under ["future-obligations", userId, ...]: the list and the
 * upcoming projection. Both are re-read from the backend; a total is never
 * adjusted locally.
 *
 * Deliberately NOT invalidated: Goals, the Savings plans overview, Expenses,
 * Accounts, Budgets and every analytics family. An obligation is a separate
 * forecast input: recording one writes no Expense or Account transaction, moves
 * no Goal progress and changes no Goal plan, so none of those can have changed.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 */
export function invalidateFutureObligationQueries(
  queryClient: QueryClient,
  userId: string | undefined,
): Promise<unknown> {
  return queryClient.invalidateQueries({ queryKey: ["future-obligations", userId] });
}
