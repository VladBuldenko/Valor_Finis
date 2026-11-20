// Query keys of the Income server state (VF-MVP-BETA-001). Both start with
// ["income", userId], so invalidating that prefix (invalidateIncomeQueries)
// refreshes the paged list AND every cached detail.
//
// The list and a detail are different shapes (pages vs. one record), so they
// must never share a key.
export const incomeKeys = {
  all: (userId: string | undefined) => ["income", userId] as const,
  list: (userId: string | undefined) => ["income", userId, "list"] as const,
  detail: (userId: string | undefined, incomeId: string) =>
    ["income", userId, "detail", incomeId] as const,
};
