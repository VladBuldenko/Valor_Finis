import { apiRequest } from "../../api/api-client";

import type {
  FutureObligation,
  FutureObligationCreateInput,
  FutureObligationUpdateInput,
  UpcomingObligations,
} from "./future-obligation.types";

/**
 * Returns the user's future obligations: active ones by next due date, then
 * archived ones. The backend derives next_due_date from the server date.
 */
export async function getFutureObligations(
  signal?: AbortSignal,
): Promise<FutureObligation[]> {
  return apiRequest<FutureObligation[]>("/api/v1/future-obligations", {
    signal,
  });
}

/**
 * Reads the upcoming-bills projection for the next 12 calendar months. A plain,
 * abortable GET: read-only, and every total, count and date is the backend's.
 * The app does no money arithmetic for it.
 */
export async function getUpcomingObligations(
  signal?: AbortSignal,
): Promise<UpcomingObligations> {
  return apiRequest<UpcomingObligations>("/api/v1/future-obligations/upcoming", {
    signal,
  });
}

/**
 * Records a future obligation. Nothing is paid, set aside or recorded as an
 * Expense. client_request_id makes a retry of the same create safe: the backend
 * returns the existing record (200) instead of adding a second one.
 */
export async function createFutureObligation(
  input: FutureObligationCreateInput,
): Promise<FutureObligation> {
  return apiRequest<FutureObligation>("/api/v1/future-obligations", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/**
 * Updates, archives (status "archived") or restores (status "active") an
 * obligation. Send only the changed fields.
 */
export async function updateFutureObligation(
  obligationId: string,
  input: FutureObligationUpdateInput,
): Promise<FutureObligation> {
  return apiRequest<FutureObligation>(
    `/api/v1/future-obligations/${obligationId}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}
