// Extracts a user-facing message from a failed FastAPI request. apiRequest
// (api-client.ts) throws `Error("API request failed: <status> <body>")`,
// where <body> is the raw response text. This never re-throws and never
// surfaces raw JSON to the user -- every branch below resolves to either a
// real backend-authored message or the caller-supplied fallback.
//
// - A domain error (e.g. 409 "Archived account cannot receive new
//   transactions.", 422 "Income currency must match the account's
//   currency to link them.", or a 404 "Income not found.") has a body
//   shaped {"detail": "<string>"} -- that string is returned as-is.
// - A FastAPI/Pydantic validation error (422) has a body shaped
//   {"detail": [...]}: an array of structured validation issues. A
//   concrete, reachable example is an impossible calendar date like
//   "2026-02-31" -- the mobile YYYY-MM-DD shape regex accepts it, but
//   FastAPI's date parser correctly rejects the actual calendar date and
//   returns a 422 with a msg explaining why. Each array item's exact shape
//   is never assumed (a malformed/differently-shaped entry is skipped, not
//   trusted) -- the first item with a non-empty string `msg` field has
//   that `msg` returned.
// - Anything else (a non-JSON body, an empty/malformed detail array, a
//   detail that is neither a usable string nor an array, or no JSON body
//   at all after the "API request failed: ..." wrapper) falls back to the
//   caller-supplied fallback message.
// - A plain Error that does not match the apiRequest failure wrapper at
//   all (e.g. a network failure) keeps its own message as-is.
// - Any non-Error value returns the fallback.
//
// Domain-neutral on purpose: it parses the shared FastAPI error envelope,
// not any one feature's rules, so every feature can surface backend errors
// the same way. ../features/accounts/account-error-message.ts delegates
// here unchanged.
export function getApiErrorMessage(error: unknown, fallback: string): string {
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
