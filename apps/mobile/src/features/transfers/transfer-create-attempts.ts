import type { AccountTransferCreateInput } from "./transfer.types";

// The logical content of a create request -- everything the backend
// compares on an idempotent replay -- in the exact normalized form that is
// sent (see prepareTransferCreatePayload in transfer-validation.ts).
// description is null when the note is blank, and a null description is
// omitted from the request.
export type TransferCreatePayload = {
  source_account_id: string;
  destination_account_id: string;
  amount: string;
  transfer_date: string;
  description: string | null;
};

// One logical create request of the create form and the client_request_id
// that identifies it on the backend.
export type TransferCreateAttempt = {
  clientRequestId: string;
  payload: TransferCreatePayload;
};

// Returns whether two normalized payloads are the same logical request.
// Compared field by field on the exact strings that are sent, so this
// matches what the backend would treat as a replay (the amount is already
// canonical, so "300" and "300.00" never reach this as different strings).
export function isSameTransferCreatePayload(
  first: TransferCreatePayload,
  second: TransferCreatePayload,
): boolean {
  return (
    first.source_account_id === second.source_account_id &&
    first.destination_account_id === second.destination_account_id &&
    first.amount === second.amount &&
    first.transfer_date === second.transfer_date &&
    first.description === second.description
  );
}

/**
 * Resolves the idempotency key for a create submission.
 *
 * A create whose response is lost may still have been committed by the
 * backend, so a retry of the SAME logical request must reuse its
 * client_request_id -- the backend then replays the existing transfer (200)
 * instead of creating a duplicate. A changed request (any of the five
 * payload fields) is a new logical request and gets a new key; reusing the
 * old one would be a backend 409 idempotency conflict.
 *
 * `attempts` holds every not-yet-successful attempt made from the current
 * create form, not just the latest one: if the user edits the form after
 * a failure and later edits it back to an earlier payload, that earlier
 * key is reused too, so an ambiguous first attempt can still never be
 * duplicated. The caller clears the list after a success, and it is
 * discarded when the form closes (component-local state).
 *
 * Parameters:
 * - attempts: attempts made so far by this form instance.
 * - payload: the normalized payload about to be sent.
 * - generateClientRequestId: UUID source for a new logical request
 *   (expo-crypto randomUUID in the app).
 * Returns:
 * - The attempt to send, and the attempt list to keep.
 */
export function resolveTransferCreateAttempt(
  attempts: readonly TransferCreateAttempt[],
  payload: TransferCreatePayload,
  generateClientRequestId: () => string,
): { attempt: TransferCreateAttempt; attempts: TransferCreateAttempt[] } {
  const existingAttempt = attempts.find((candidate) =>
    isSameTransferCreatePayload(candidate.payload, payload),
  );

  if (existingAttempt) {
    return { attempt: existingAttempt, attempts: [...attempts] };
  }

  const newAttempt: TransferCreateAttempt = {
    clientRequestId: generateClientRequestId(),
    payload,
  };

  return { attempt: newAttempt, attempts: [...attempts, newAttempt] };
}

// Builds the request body for an attempt. A null description is omitted,
// never sent as "" -- the backend compares description as-is on replay, so
// the same convention must hold on every retry.
export function toAccountTransferCreateInput(
  attempt: TransferCreateAttempt,
): AccountTransferCreateInput {
  const { description, ...payload } = attempt.payload;

  return {
    client_request_id: attempt.clientRequestId,
    ...payload,
    ...(description !== null ? { description } : {}),
  };
}
