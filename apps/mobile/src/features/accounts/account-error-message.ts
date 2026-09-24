// Extracts a user-facing message from a failed Account-related request
// (update, delete, or transaction create). apiRequest (api-client.ts)
// throws `Error("API request failed: <status> <body>")`, where <body> is
// the raw response text. This never re-throws and never surfaces raw
// JSON to the user -- every branch below resolves to either a real
// backend-authored message or the caller-supplied fallback.
//
// - A domain error (e.g. 409 "Account currency cannot be changed after
//   transaction history exists.", 409 "Account with transaction history
//   cannot be deleted. Archive it instead.", 409 "Archived account
//   cannot receive new transactions.", or a 404 "Account not found.")
//   has a body shaped {"detail": "<string>"} -- that string is returned
//   as-is.
// - A FastAPI/Pydantic validation error (422) has a body shaped
//   {"detail": [...]}: an array of structured validation issues. A
//   concrete, reachable example is an impossible calendar date like
//   "2026-02-31" -- the mobile YYYY-MM-DD shape regex accepts it, but
//   FastAPI's date parser correctly rejects the actual calendar date
//   and returns a 422 with a msg explaining why. Each array item's exact
//   shape is never assumed (a malformed/differently-shaped entry is
//   skipped, not trusted) -- the first item with a non-empty string
//   `msg` field has that `msg` returned.
// - Anything else (a non-JSON body, an empty/malformed detail array, a
//   detail that is neither a usable string nor an array, or no match
//   for the "API request failed: ..." wrapper's JSON body at all) falls
//   back to the caller-supplied fallback message.
// - A plain Error that does not match the apiRequest failure wrapper at
//   all (e.g. a network failure) keeps its own message as-is.
// - Any non-Error value returns the fallback.
//
// Shared across account-edit-screen.tsx, accounts-screen.tsx (delete),
// and account-detail-screen.tsx (archive/reactivate, adjustments) so
// every Account mutation flow surfaces backend errors the same way.
// Deliberately NOT an exact mirror of ../goals/goal-error-message.ts
// (anymore): this handles FastAPI validation-error arrays, which Goal's
// helper does not -- generalizing that improvement back into Goal is a
// separate, later task, not part of this fix.
export function getAccountErrorMessage(
  error: unknown,
  fallback: string,
): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  const match = error.message.match(/^API request failed: \d+ (.*)$/s);

  if (!match) {
    return error.message;
  }

  let body: unknown;

  try {
    body = JSON.parse(match[1]);
  } catch {
    return fallback;
  }

  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string" && detail) {
    return detail;
  }

  if (Array.isArray(detail)) {
    for (const item of detail) {
      const msg = (item as { msg?: unknown } | null)?.msg;

      if (typeof msg === "string" && msg) {
        return msg;
      }
    }
  }

  return fallback;
}
