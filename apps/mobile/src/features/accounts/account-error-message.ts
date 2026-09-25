import { getApiErrorMessage } from "../../api/api-error-message";

// Extracts a user-facing message from a failed Account-related request
// (create, update, archive/reactivate, delete, or transaction create).
// Kept as a named Account entry point so existing callers
// (account-create-screen.tsx, account-edit-screen.tsx,
// account-detail-screen.tsx) stay unchanged,
// but the parsing itself now lives in the domain-neutral
// ../../api/api-error-message.ts (VF-017G) -- behavior is identical:
// {"detail": "<string>"} returns that string, {"detail": [{msg}, ...]}
// returns the first non-empty msg, a plain non-API Error keeps its own
// message, and anything else (non-Error, non-JSON body, malformed detail)
// returns the fallback. Raw JSON is never surfaced to the user.
//
// Deliberately NOT an exact mirror of ../goals/goal-error-message.ts: that
// helper does not handle FastAPI validation-error arrays -- generalizing
// Goal onto the shared helper is a separate, later task.
export function getAccountErrorMessage(
  error: unknown,
  fallback: string,
): string {
  return getApiErrorMessage(error, fallback);
}
