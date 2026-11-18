import type { QueryClient } from "@tanstack/react-query";
import { invalidateReconciliationQueries } from "../future-obligations/future-obligation-link-cache.ts";
import { invalidateGoalHistoryQueries } from "../goals/goal-cache.ts";

/**
 * Invalidates the server-state caches affected by a successful Expense
 * create/update/delete.
 *
 * Always invalidated: ["expenses", userId] and every analytics family an
 * Expense feeds (monthly/category summaries, budget status, spending and
 * category trends, spending forecast, and the Financial Overview and its
 * income-expense trend). These are prefix matches, so every cached
 * period/count variant is covered. Receipt confirmation creates an
 * Expense and refreshes through this same helper.
 *
 * The Account caches are invalidated only when the mutation touched an
 * Account ledger, i.e. when the Expense was linked before OR is linked
 * after the mutation (linked create, attach, detach, move, a linked
 * amount/date/currency correction, or deleting a linked Expense): the
 * backend creates/updates/removes the Expense's debit AccountTransaction
 * projection, which changes the Account's ledger-derived current_balance
 * and its transaction history. The history invalidation is a prefix match
 * on ["accounts", "transactions", userId], so a move refreshes BOTH the
 * source and destination Account histories.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 * - touchedAccount: true when the previous or resulting account_id is
 *   non-null.
 */
export function invalidateExpenseQueries(
  queryClient: QueryClient,
  userId: string | undefined,
  touchedAccount: boolean,
): Promise<unknown> {
  const invalidations: Promise<unknown>[] = [
    queryClient.invalidateQueries({ queryKey: ["expenses", userId] }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "monthly-summary", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "category-summary", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "budget-status", userId],
    }),
    // VF-015B/C/D: an Expense change affects historical/category trends
    // and the current-month forecast too.
    queryClient.invalidateQueries({
      queryKey: ["analytics", "spending-trend", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "category-trend", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "spending-forecast", userId],
    }),
    // VF-019B/C: Financial Overview counts every Expense, linked or not.
    queryClient.invalidateQueries({
      queryKey: ["analytics", "financial-overview", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "income-expense-trend", userId],
    }),
    // VF-GOALS-PLANNING-002A/002B: every Goal's comparison with recorded history
    // and the combined savings overview average Income and Expenses, so both
    // are re-read. The Goal plan and the Goal lists are unaffected.
    invalidateGoalHistoryQueries(queryClient, userId),
    // VF-GOALS-PLANNING-002C2: a linked expense's title and date are shown on its bill date
    // and a new or changed expense may now be one that can be linked, so only the link
    // views are re-read. The bills list and the upcoming projection are untouched:
    // an Expense never changes a bill.
    invalidateReconciliationQueries(queryClient, userId),
  ];

  if (touchedAccount) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["accounts", userId] }),
      queryClient.invalidateQueries({
        queryKey: ["accounts", "transactions", userId],
      }),
    );
  }

  return Promise.all(invalidations);
}
