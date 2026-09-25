import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the server-state caches affected by a successful Income
 * mutation.
 *
 * ["income", userId] is always invalidated. The Account caches are
 * invalidated only when the mutation touched an Account ledger, i.e.
 * when the Income was linked before OR is linked after the mutation
 * (attach, detach, move, a linked amount/date correction, or deleting a
 * linked Income): the backend creates/updates/removes the Income's
 * AccountTransaction projection, which changes the Account's
 * ledger-derived current_balance and its transaction history.
 *
 * The history invalidation is a prefix match on
 * ["accounts", "transactions", userId] so a move refreshes BOTH the
 * source and destination Account histories. Analytics is never
 * invalidated -- no Analytics endpoint consumes Income today.
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
