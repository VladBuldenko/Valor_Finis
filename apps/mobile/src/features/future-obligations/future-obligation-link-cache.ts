import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the caches that show which expense is linked to which bill date:
 * the reconciliation overview and the candidate lists. Both are re-read from the
 * backend; a link is never added or removed locally.
 *
 * Used after a link or an unlink, and after any Expense change (a new expense can
 * become a candidate, an edited title or date is shown on a linked bill date, and
 * a deleted expense can no longer be one).
 *
 * Deliberately NOT invalidated: the bills list and the upcoming projection. A link
 * changes neither: the schedule and its totals are the user's forecast and are
 * never reduced by a linked expense. A bill edit refreshes everything through
 * invalidateFutureObligationQueries (the whole ["future-obligations", userId]
 * family, which includes these two). Goals, Accounts, Budgets and analytics are
 * untouched too: a link writes no expense, no account transaction and no Goal row.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 */
export function invalidateReconciliationQueries(
  queryClient: QueryClient,
  userId: string | undefined,
): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["future-obligations", userId, "reconciliation"] }),
    queryClient.invalidateQueries({ queryKey: ["future-obligations", userId, "candidates"] }),
  ]);
}
