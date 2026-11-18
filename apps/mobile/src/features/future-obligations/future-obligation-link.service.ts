import { apiRequest } from "../../api/api-client";

import type {
  OccurrenceCandidates,
  OccurrenceLink,
  OccurrenceLinkInput,
  ReconciliationOverview,
} from "./future-obligation-link.types";

/**
 * Reads the bounded overview of bill dates and their link status: the previous
 * three months, this month and the 12-month horizon. A plain, abortable GET;
 * every date, amount and link is the backend's.
 */
export async function getReconciliationOverview(
  signal?: AbortSignal,
): Promise<ReconciliationOverview> {
  return apiRequest<ReconciliationOverview>("/api/v1/future-obligations/reconciliation", {
    signal,
  });
}

/**
 * Reads the expenses that can be linked to one bill date (same currency, exact
 * same amount, not linked yet, not dated in the future) plus counts of the
 * others. The user chooses: nothing is matched automatically.
 */
export async function getOccurrenceCandidates(
  obligationId: string,
  dueDate: string,
  signal?: AbortSignal,
): Promise<OccurrenceCandidates> {
  return apiRequest<OccurrenceCandidates>(
    `/api/v1/future-obligations/${obligationId}/occurrence-candidates?due_date=${encodeURIComponent(dueDate)}`,
    { signal },
  );
}

/**
 * Links one bill date to an existing expense. Repeating the same request is safe
 * (the backend answers with the existing link). Nothing is paid or created.
 */
export async function linkOccurrence(
  obligationId: string,
  input: OccurrenceLinkInput,
): Promise<OccurrenceLink> {
  return apiRequest<OccurrenceLink>(
    `/api/v1/future-obligations/${obligationId}/occurrence-links`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

/** Removes a link. The expense and the bill are not changed. */
export async function unlinkOccurrence(
  obligationId: string,
  linkId: string,
): Promise<void> {
  return apiRequest<void>(
    `/api/v1/future-obligations/${obligationId}/occurrence-links/${linkId}`,
    { method: "DELETE" },
  );
}
