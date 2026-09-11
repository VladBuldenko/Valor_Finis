import { apiRequest } from "../../api/api-client";

import type {
  BudgetStatusItem,
  CategorySummaryItem,
  GoalProgressItem,
  MonthlySummary,
} from "./analytics.types";

/**
 * Returns the authenticated user's spending summary
 * for the selected calendar month.
 */
export async function getMonthlySummary(
  year: number,
  month: number,
): Promise<MonthlySummary> {
  return apiRequest<MonthlySummary>(
    `/api/v1/analytics/monthly-summary?year=${year}&month=${month}`,
  );
}

/**
 * Returns the authenticated user's spending grouped by category
 * for the selected calendar month.
 */
export async function getCategorySummary(
  year: number,
  month: number,
): Promise<CategorySummaryItem[]> {
  return apiRequest<CategorySummaryItem[]>(
    `/api/v1/analytics/category-summary?year=${year}&month=${month}`,
  );
}

/**
 * Returns the authenticated user's budget status.
 */
export async function getBudgetStatus(): Promise<BudgetStatusItem[]> {
  return apiRequest<BudgetStatusItem[]>(
    "/api/v1/analytics/budget-status",
  );
}

/**
 * Returns the authenticated user's financial goal progress.
 */
export async function getGoalProgress(): Promise<GoalProgressItem[]> {
  return apiRequest<GoalProgressItem[]>(
    "/api/v1/analytics/goal-progress",
  );
}