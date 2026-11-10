// Create idempotency on the client (VF-MVP-CORE-002), shared by the Income and
// Expense create forms. Pure and dependency-free (no React Native, no network)
// so the key lifecycle is tested in Node.
//
// A create whose response is lost may still have been committed by the backend,
// so a retry of the SAME logical request must reuse its client_request_id: the
// backend then replays the existing record (200) instead of creating a
// duplicate. A different request is a new logical operation and gets a new key;
// reusing the old one would be a backend 409 idempotency conflict.

// One logical create request of a form instance and the key that identifies it.
export type CreateAttempt<Payload> = {
  readonly clientRequestId: string;
  // The signed-in user the attempt was made for. An attempt of another user is
  // never reused (the backend scopes keys per user anyway; this keeps the client
  // from carrying one user's pending operation into another session).
  readonly scope: string;
  // Canonical text of the payload (see the per-domain key functions): equal keys
  // mean the same logical request.
  readonly key: string;
  readonly payload: Payload;
};

/**
 * Resolves the idempotency key for a create submission.
 *
 * `attempts` holds every not-yet-successful attempt made from the current form,
 * not just the latest one: if the user edits the form after an outcome-unknown
 * failure and later edits it back to an earlier payload, that earlier key is
 * reused too, so an ambiguous first attempt can still never be duplicated. The
 * caller clears the list after a success, and it is discarded when the form
 * closes (component-local state).
 *
 * Parameters:
 * - attempts: attempts made so far by this form instance.
 * - scope: the current user's id.
 * - key: canonical text of the normalized payload about to be sent.
 * - payload: the normalized payload about to be sent.
 * - generateClientRequestId: UUID source for a new logical request (expo-crypto
 *   randomUUID in the app).
 * Returns:
 * - The attempt to send, and the attempt list to keep.
 */
export function resolveCreateAttempt<Payload>(
  attempts: readonly CreateAttempt<Payload>[],
  scope: string,
  key: string,
  payload: Payload,
  generateClientRequestId: () => string,
): { attempt: CreateAttempt<Payload>; attempts: CreateAttempt<Payload>[] } {
  const ownAttempts = attempts.filter((candidate) => candidate.scope === scope);
  const existingAttempt = ownAttempts.find((candidate) => candidate.key === key);

  if (existingAttempt) {
    return { attempt: existingAttempt, attempts: ownAttempts };
  }

  const newAttempt: CreateAttempt<Payload> = {
    clientRequestId: generateClientRequestId(),
    scope,
    key,
    payload,
  };

  return { attempt: newAttempt, attempts: [...ownAttempts, newAttempt] };
}

/**
 * A synchronous single-flight guard for a submit handler.
 *
 * `mutation.isPending` only turns true after React re-renders, so two taps
 * delivered before that render would both pass an `isPending` check and send
 * two requests. This guard flips synchronously: the first `tryEnter()` wins and
 * every later one is refused until `release()`.
 */
export function createSubmitGuard(): { tryEnter: () => boolean; release: () => void; isBusy: () => boolean } {
  let busy = false;

  return {
    tryEnter(): boolean {
      if (busy) {
        return false;
      }

      busy = true;

      return true;
    },
    release(): void {
      busy = false;
    },
    isBusy: (): boolean => busy,
  };
}
