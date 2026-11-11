import type { CreateAttempt } from "../../lib/create-attempts.ts";
import type { ExpenseCreateInput } from "./expense.types.ts";

// The logical content of an Expense create request: everything the backend
// compares on an idempotent replay, in the exact normalized form that is sent.
export type ExpenseCreatePayload = Omit<ExpenseCreateInput, "client_request_id">;

// Canonical text of a payload; equal text = the same logical request. An
// omitted optional field is the same as null (the form builds its payload the
// same way every time).
export function expensePayloadKey(payload: ExpenseCreatePayload): string {
  return JSON.stringify([
    "expense.create",
    payload.category_id ?? null,
    payload.title,
    payload.amount,
    payload.currency,
    payload.expense_date,
    payload.description ?? null,
    payload.source ?? null,
    payload.account_id ?? null,
  ]);
}

// Builds the request body for an attempt: the payload plus its key.
export function toExpenseCreateInput(attempt: CreateAttempt<ExpenseCreatePayload>): ExpenseCreateInput {
  return { ...attempt.payload, client_request_id: attempt.clientRequestId };
}
