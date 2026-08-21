import { apiRequest } from "../../api/api-client";

import type {
  CategorySummaryItem,
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
 * Returns the authenticated user's spending grouped by category.
 */
export async function getCategorySummary(): Promise<
  CategorySummaryItem[]
> {
  return apiRequest<CategorySummaryItem[]>(
    "/api/v1/analytics/category-summary",
  );
}