import type { CreateAttempt } from "../../lib/create-attempts.ts";
import type { FutureObligationCreateInput } from "./future-obligation.types.ts";

// The logical content of a create request: everything the backend compares on an
// idempotent replay, in the exact normalized form that is sent.
export type FutureObligationCreatePayload = Omit<FutureObligationCreateInput, "client_request_id">;

// Canonical text of a payload; equal text = the same logical request. An omitted
// optional field is the same as null (the form omits a blank one every time).
export function futureObligationPayloadKey(payload: FutureObligationCreatePayload): string {
  return JSON.stringify([
    "future-obligation.create",
    payload.name,
    payload.schedule,
    payload.amount,
    payload.currency ?? null,
    payload.first_due_date,
    payload.final_due_date ?? null,
    payload.description ?? null,
  ]);
}

// Builds the request body for an attempt: the payload plus its key.
export function toFutureObligationCreateInput(
  attempt: CreateAttempt<FutureObligationCreatePayload>,
): FutureObligationCreateInput {
  return { ...attempt.payload, client_request_id: attempt.clientRequestId };
}
