import { apiRequest } from "../../api/api-client";

import type { MonthlySummary } from "./analytics.types";
import { resolve } from "path";

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