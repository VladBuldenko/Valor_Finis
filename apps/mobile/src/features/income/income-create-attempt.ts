import type { CreateAttempt } from "../../lib/create-attempts.ts";
import type { IncomeCreateInput } from "./income.types.ts";

// The logical content of an Income create request: everything the backend
// compares on an idempotent replay, in the exact normalized form that is sent.
export type IncomeCreatePayload = Omit<IncomeCreateInput, "client_request_id">;

// Canonical text of a payload; equal text = the same logical request. An
// omitted description or account is the same as null (the form omits a blank
// note and "No account" the same way every time).
export function incomePayloadKey(payload: IncomeCreatePayload): string {
  return JSON.stringify([
    "income.create",
    payload.amount,
    payload.currency,
    payload.received_at,
    payload.source,
    payload.description ?? null,
    payload.account_id ?? null,
  ]);
}

// Builds the request body for an attempt: the payload plus its key.
export function toIncomeCreateInput(attempt: CreateAttempt<IncomeCreatePayload>): IncomeCreateInput {
  return { ...attempt.payload, client_request_id: attempt.clientRequestId };
}
