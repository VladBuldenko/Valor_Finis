// Extracts a user-facing message from a failed Account-related request
// (update, delete, or transaction create). apiRequest (api-client.ts)
// throws `Error("API request failed: <status> <body>")`, where <body> is
// the raw response text -- for domain errors (e.g. 409 "Account currency
// cannot be changed after transaction history exists.", 409 "Account with
// transaction history cannot be deleted. Archive it instead.", 409
// "Archived account cannot receive new transactions.", or a 404 "Account
// not found.") that body is FastAPI JSON with a string "detail" field.
// When it parses that way, the backend's own detail text is shown instead
// of the raw "API request failed: ..." wrapper, so a domain error reads as
// a normal message rather than a technical one. Falls back to the given
// default otherwise (e.g. a network failure has no such body, or a 422's
// detail is a structured list rather than a string) -- this intentionally
// never invents new error copy that could drift from what the backend
// actually says. Exact mirror of ../goals/goal-error-message.ts.
//
// Shared across account-edit-screen.tsx, accounts-screen.tsx (delete),
// and account-detail-screen.tsx (archive/reactivate, adjustments) so
// every Account mutation flow surfaces backend errors the same way.
export function getAccountErrorMessage(
  error: unknown,
  fallback: string,
): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  const match = error.message.match(/^API request failed: \d+ (.*)$/s);

  if (match) {
    try {
      const body = JSON.parse(match[1]) as { detail?: unknown };

      if (typeof body.detail === "string") {
        return body.detail;
      }
    } catch {
      // Response body wasn't JSON -- fall through to the raw message below.
    }
  }

  return error.message;
}
