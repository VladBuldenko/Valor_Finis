import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates the server-state caches affected by a successful transfer
 * mutation.
 *
 * ["account-transfers", userId] is always invalidated. The Account caches
 * are invalidated only when the mutation may have touched the ledger: a
 * create that came back posted, a manual post, and a delete (callers pass
 * true for every delete, because a cached "planned" status may be stale if
 * the transfer was posted elsewhere). A planned create writes no ledger
 * rows, so it leaves the Account caches alone.
 *
 * The history invalidation is a prefix match on
 * ["accounts", "transactions", userId], so BOTH Accounts' histories are
 * refreshed. Balances always come from that refetch -- never computed
 * locally. Income, expenses, analytics, budgets, and goals are never
 * affected by transfers and are never invalidated here.
 *
 * Parameters:
 * - queryClient: the app's TanStack QueryClient.
 * - userId: the authenticated user's id (part of every query key).
 * - touchedLedger: true when the mutation may have added or removed
 *   transfer ledger rows.
 */
export function invalidateTransferQueries(
  queryClient: QueryClient,
  userId: string | undefined,
  touchedLedger: boolean,
): Promise<unknown> {
  const invalidations: Promise<unknown>[] = [
    queryClient.invalidateQueries({ queryKey: ["account-transfers", userId] }),
  ];

  if (touchedLedger) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["accounts", userId] }),
      queryClient.invalidateQueries({
        queryKey: ["accounts", "transactions", userId],
      }),
    );
  }

  return Promise.all(invalidations);
}
