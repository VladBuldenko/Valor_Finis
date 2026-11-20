// Query keys of the Expenses server state (VF-MVP-BETA-001). Both start with
// ["expenses", userId], so invalidating that prefix (invalidateExpenseQueries,
// category deletion) refreshes the paged list AND every cached detail.
//
// The list and a detail are different shapes (pages vs. one record), so they
// must never share a key.
export const expenseKeys = {
  all: (userId: string | undefined) => ["expenses", userId] as const,
  list: (userId: string | undefined) => ["expenses", userId, "list"] as const,
  detail: (userId: string | undefined, expenseId: string) =>
    ["expenses", userId, "detail", expenseId] as const,
};
