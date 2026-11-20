import { apiRequest } from "../../api/api-client";

import { pagedPath, type Page } from "../../lib/paged-list";
import type {
  Income,
  IncomeCreateInput,
  IncomeUpdateInput,
} from "./income.types";

/**
 * Returns ONE page of the authenticated user's Income records, newest
 * received_at first, with the user's total number of Income records. The page
 * is requested explicitly (limit/offset); a request without them would return
 * the complete bare list.
 */
export async function getIncomePage(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<Page<Income>> {
  return apiRequest<Page<Income>>(
    pagedPath("/api/v1/income", limit, offset),
    { signal },
  );
}

/**
 * Returns one Income of the authenticated user. This is how the edit screen
 * opens an Income that is not on any loaded page; an id that does not exist
 * and an id of another user are both a 404.
 */
export async function getIncomeById(
  incomeId: string,
  signal?: AbortSignal,
): Promise<Income> {
  return apiRequest<Income>(`/api/v1/income/${incomeId}`, { signal });
}

/**
 * Creates an Income for the authenticated user. When account_id is
 * present the backend atomically creates the linked Account credit as
 * well.
 */
export async function createIncome(
  incomeData: IncomeCreateInput,
): Promise<Income> {
  return apiRequest<Income>("/api/v1/income", {
    method: "POST",
    body: JSON.stringify(incomeData),
  });
}

/**
 * Updates an Income owned by the authenticated user. The payload must
 * contain only changed fields (see IncomeUpdateInput for account_id's
 * three-state semantics).
 */
export async function updateIncome(
  incomeId: string,
  incomeData: IncomeUpdateInput,
): Promise<Income> {
  return apiRequest<Income>(`/api/v1/income/${incomeId}`, {
    method: "PATCH",
    body: JSON.stringify(incomeData),
  });
}

/**
 * Deletes an Income owned by the authenticated user. The backend removes
 * any linked Account credit in the same transaction, so the client never
 * touches Account transactions directly. Returns 204 No Content.
 */
export async function deleteIncome(incomeId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/income/${incomeId}`, {
    method: "DELETE",
  });
}
