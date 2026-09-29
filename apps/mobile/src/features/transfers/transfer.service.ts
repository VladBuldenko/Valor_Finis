import { apiRequest } from "../../api/api-client";

import type {
  AccountTransfer,
  AccountTransferCreateInput,
  AccountTransferPostInput,
} from "./transfer.types";

/**
 * Returns every transfer of the authenticated user, planned and posted, in
 * the backend's order (COALESCE(effective_date, planned_date) DESC, then
 * created_at DESC, then id DESC) -- never re-sorted client-side. There is
 * no GET /account-transfers/{id}; screens resolve a transfer from this
 * list.
 */
export async function getAccountTransfers(): Promise<AccountTransfer[]> {
  return apiRequest<AccountTransfer[]>("/api/v1/account-transfers");
}

/**
 * Creates a transfer, idempotently. The backend answers 201 for a new
 * transfer and 200 for an exact replay of an already-created one (same
 * client_request_id and payload); both carry the transfer's CURRENT state,
 * so both are treated as the same success here.
 */
export async function createAccountTransfer(
  payload: AccountTransferCreateInput,
): Promise<AccountTransfer> {
  return apiRequest<AccountTransfer>("/api/v1/account-transfers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Manually posts a planned transfer with an explicit effective_date. The
 * backend owns the planned -> posted transition and creates both ledger
 * rows; posting is not idempotent (a repeated post is a 409).
 */
export async function postAccountTransfer(
  transferId: string,
  payload: AccountTransferPostInput,
): Promise<AccountTransfer> {
  return apiRequest<AccountTransfer>(
    `/api/v1/account-transfers/${transferId}/post`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

// apiRequest (api-client.ts) throws Error("API request failed: <status>
// <body>"); this recognizes a 404 from that wrapper only.
function isNotFoundApiError(error: unknown): boolean {
  return (
    error instanceof Error && /^API request failed: 404 /.test(error.message)
  );
}

/**
 * Hard-deletes a planned or posted transfer (the backend removes a posted
 * transfer's ledger rows itself). A 404 is treated as success: the ids come
 * from the user's own transfer list, so a missing transfer was already
 * deleted -- e.g. a retry after a lost response, or a delete from another
 * device (account-transfers contract, section 26).
 */
export async function deleteAccountTransfer(transferId: string): Promise<void> {
  try {
    await apiRequest<void>(`/api/v1/account-transfers/${transferId}`, {
      method: "DELETE",
    });
  } catch (error) {
    if (isNotFoundApiError(error)) {
      return;
    }

    throw error;
  }
}
