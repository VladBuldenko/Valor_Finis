import { apiRequest } from "../../api/api-client";

import type {
  Income,
  IncomeCreateInput,
  IncomeUpdateInput,
} from "./income.types";

/**
 * Returns Income records owned by the authenticated user, newest
 * received_at first. There is no GET /income/{id} endpoint -- the edit
 * screen resolves a single Income from this list.
 */
export async function getIncome(): Promise<Income[]> {
  return apiRequest<Income[]>("/api/v1/income");
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
