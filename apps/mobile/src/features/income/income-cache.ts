import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the server-state caches affected by a successful Income
 * mutation.
 *
 * ["income", userId] is always invalidated, and so are the two Financial
 * Overview analytics families (VF-019B/C) -- ["analytics",
 * "financial-overview", userId] and ["analytics", "income-expense-trend",
 * userId] -- because every Income counts toward them whether or not it is
 * linked to an Account. These are prefix matches, so every cached month/
 * count variant is covered. No other analytics endpoint consumes Income.
 *
 * The Account caches are invalidated only when the mutation touched an
 * Account ledger, i.e. when the Income was linked before OR is linked
 * after the mutation (attach, detach, move, a linked amount/date
 * correction, or deleting a linked Income): the backend creates/updates/
 * removes the Income's AccountTransaction projection, which changes the
 * Account's ledger-derived current_balance and its transaction history.
 *
 * The history invalidation is a prefix match on
 * ["accounts", "transactions", userId] so a move refreshes BOTH the
 * source and destination Account histories.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 * - touchedAccount: true when the previous or resulting account_id is
 *   non-null.
 */
export function invalidateIncomeQueries(
  queryClient: QueryClient,
  userId: string | undefined,
  touchedAccount: boolean,
): Promise<unknown> {
  const invalidations: Promise<unknown>[] = [
    queryClient.invalidateQueries({ queryKey: ["income", userId] }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "financial-overview", userId],
    }),
    queryClient.invalidateQueries({
      queryKey: ["analytics", "income-expense-trend", userId],
    }),
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
