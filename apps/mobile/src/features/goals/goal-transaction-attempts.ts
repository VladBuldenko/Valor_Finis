import type {
  GoalTransaction,
  GoalTransactionCreateInput,
} from "./goal.types";

// The logical content of a goal transaction create request -- everything
// the backend compares on an idempotent replay (VF-020B3) -- in the exact
// form that is sent. amount is canonical (see canonicalizeGoalAmount) and
// description is null when the note is blank; a null description is
// omitted from the request. effective_date is deliberately not part of it:
// this client never sends one, so the server assigns the date and a retry
// after midnight still replays the original transaction.
export type GoalTransactionPayload = {
  goalId: string;
  type: "contribution" | "withdrawal";
  amount: string;
  description: string | null;
};

// One logical create request of the goal detail form and the
// client_request_id that identifies it on the backend.
export type GoalTransactionAttempt = {
  clientRequestId: string;
  payload: GoalTransactionPayload;
};

// Canonicalizes an already validated amount string (digits, optional "."
// and 1-2 decimals -- see validateGoalDecimalAmount) to a fixed two-decimal
// form: "10" -> "10.00", "10.5" -> "10.50", "010.00" -> "10.00". The
// backend compares amounts as Decimal values, so "10" and "10.00" are the
// same request there; canonicalizing makes them the same request here too.
// String operations only -- the amount is never parsed into a JavaScript
// Number.
export function canonicalizeGoalAmount(amount: string): string {
  const [integerPart, fractionPart = ""] = amount.split(".");
  const integer = integerPart.replace(/^0+(?=\d)/, "");

  return `${integer}.${fractionPart.padEnd(2, "0")}`;
}

// Returns whether two payloads are the same logical request, compared
// field by field on the exact values that are sent.
export function isSameGoalTransactionPayload(
  first: GoalTransactionPayload,
  second: GoalTransactionPayload,
): boolean {
  return (
    first.goalId === second.goalId &&
    first.type === second.type &&
    first.amount === second.amount &&
    first.description === second.description
  );
}

/**
 * Resolves the idempotency key for a goal transaction submission.
 *
 * A contribution or withdrawal whose response is lost may still have been
 * committed by the backend, so a retry of the SAME logical request must
 * reuse its client_request_id -- the backend then replays the existing
 * transaction (200) instead of creating a duplicate. A changed request
 * (goal, type, amount or note) is a new logical request and gets a new
 * key; reusing the old one would be a backend 409 idempotency conflict.
 *
 * `attempts` holds every not-yet-successful attempt made from the current
 * form, not just the latest one: if the user edits the form after a
 * failure and later edits it back to an earlier payload, that earlier key
 * is reused too, so an ambiguous first attempt can still never be
 * duplicated. The caller clears the list after a success, and it is
 * discarded when the screen closes (component-local state).
 *
 * Parameters:
 * - attempts: attempts made so far by this form instance.
 * - payload: the payload about to be sent.
 * - generateClientRequestId: UUID source for a new logical request
 *   (expo-crypto randomUUID in the app).
 * Returns:
 * - The attempt to send, and the attempt list to keep.
 */
export function resolveGoalTransactionAttempt(
  attempts: readonly GoalTransactionAttempt[],
  payload: GoalTransactionPayload,
  generateClientRequestId: () => string,
): { attempt: GoalTransactionAttempt; attempts: GoalTransactionAttempt[] } {
  const existingAttempt = attempts.find((candidate) =>
    isSameGoalTransactionPayload(candidate.payload, payload),
  );

  if (existingAttempt) {
    return { attempt: existingAttempt, attempts: [...attempts] };
  }

  const newAttempt: GoalTransactionAttempt = {
    clientRequestId: generateClientRequestId(),
    payload,
  };

  return { attempt: newAttempt, attempts: [...attempts, newAttempt] };
}

// Builds the request body for an attempt. goalId travels in the URL path,
// not the body. A null description is omitted, never sent as "" -- the
// backend compares description as-is on replay, so the same convention
// must hold on every retry. effective_date is never sent (see
// GoalTransactionPayload).
export function toGoalTransactionCreateInput(
  attempt: GoalTransactionAttempt,
): GoalTransactionCreateInput {
  const { type, amount, description } = attempt.payload;

  return {
    client_request_id: attempt.clientRequestId,
    type,
    amount,
    ...(description !== null ? { description } : {}),
  };
}

// Returns the date to show for a goal transaction: its business date
// (effective_date, "YYYY-MM-DD") when present, else created_at for history
// recorded before effective_date existed. Both are returned as the exact
// strings the backend sent and are never parsed into a Date, so a
// date-only value can never shift to the previous or next day through a
// timezone conversion.
export function getGoalTransactionDisplayDate(
  transaction: Pick<GoalTransaction, "effective_date" | "created_at">,
): string {
  return transaction.effective_date ?? transaction.created_at;
}
