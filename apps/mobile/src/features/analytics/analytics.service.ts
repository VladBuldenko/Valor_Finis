import { apiRequest } from "../../api/api-client";

import type {
  BudgetStatusItem,
  CategorySummaryItem,
  CategoryTrendResponse,
  GoalProgressItem,
  MonthlySummary,
  SpendingForecastResponse,
  SpendingTrendPeriod,
  SpendingTrendResponse,
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

/**
 * Returns the authenticated user's bounded historical base-currency
 * spending trend (VF-015B) - a day/week/month bucket series ending with
 * the current period, plus a comparison between the two most recent
 * complete periods.
 *
 * `count` is optional -- the backend applies its own per-period default
 * (30/12/6 for day/week/month) when omitted. This function never
 * duplicates that default client-side.
 */
export async function getSpendingTrend(
  period: SpendingTrendPeriod,
  count?: number,
): Promise<SpendingTrendResponse> {
  const params = new URLSearchParams({ period });

  if (count !== undefined) {
    params.set("count", String(count));
  }

  return apiRequest<SpendingTrendResponse>(
    `/api/v1/analytics/spending-trend?${params.toString()}`,
  );
}

/**
 * Returns the authenticated user's bounded historical base-currency
 * spending trend grouped by category (VF-015C) - the same bucket/
 * comparison shape as getSpendingTrend, once per category.
 *
 * `count` follows the same backend default as getSpendingTrend when
 * omitted. `categoryId` is supported because the backend contract
 * supports it, even though the VF-015E screen does not yet expose a
 * per-category filter in the UI.
 */
export async function getCategoryTrend(
  period: SpendingTrendPeriod,
  count?: number,
  categoryId?: string,
): Promise<CategoryTrendResponse> {
  const params = new URLSearchParams({ period });

  if (count !== undefined) {
    params.set("count", String(count));
  }

  if (categoryId !== undefined) {
    params.set("category_id", categoryId);
  }

  return apiRequest<CategoryTrendResponse>(
    `/api/v1/analytics/category-trend?${params.toString()}`,
  );
}

/**
 * Returns the authenticated user's deterministic current-month spending
 * pace projection (VF-015D). Always covers the calendar month containing
 * the server's current date -- there is no query parameter to select a
 * different month, history length, or forecast model.
 */
export async function getSpendingForecast(): Promise<SpendingForecastResponse> {
  return apiRequest<SpendingForecastResponse>(
    "/api/v1/analytics/spending-forecast",
  );
}