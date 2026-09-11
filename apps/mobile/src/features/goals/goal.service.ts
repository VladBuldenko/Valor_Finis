import { apiRequest } from "../../api/api-client";

import type { Goal } from "./goal.types";

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
