# Mobile API client (VF-MF-2)

Scope: `apps/mobile/src/api`, `src/lib/session-runtime.ts`, `src/lib/query-client.ts`, `src/features/auth/navigation-intent.ts`.
The backend is unchanged. Verification is by Node tests only (`npm test`); the staging drills of gate BR-7 (expired
token, hung request) and device checks are NOT done by this task.

## Call path

```text
screen -> feature service -> apiRequest (api-client.ts) -> api-transport.ts -> fetch -> FastAPI
                                                 |-> session-lifecycle.ts (HTTP 401)
                                                 `-> session-boundary.ts  (user change)
```

`apiRequest<T>(path, options)` keeps its signature (`RequestInit` plus an optional `timeoutMs`) and a new optional
`signal`. `api-transport.ts` has no Supabase or React Native import; everything environmental is injected, which is
what the tests use.

## Timeouts and cancellation

- One overall deadline per call: **30 s**, **60 s** when the body is `FormData`. It covers the session lookup, every
  attempt, the retry waits and reading the response body. The deadline is a hard bound (the awaited operation is raced
  against the abort signal, so it holds even if `fetch` ignores the signal).
- Cancellation: the caller's `signal`, the deadline, and a user change all abort one internal `AbortController`. An
  already-aborted caller signal sends nothing. Listeners and the timer are removed on every exit path.
- The session `Authorization` header is set last on a case-insensitive `Headers` object; a caller cannot replace it.
  `FormData` requests never carry a manual `Content-Type`; 204 returns `undefined`.
- A timeout does not mean the server did nothing: for a mutation the outcome is unknown. The user must check before
  repeating it (the goal contribution flow already protects retries with `client_request_id`).

## Errors

`ApiError` (`api-error.ts`) has `kind`, `status`, `detail`, `code`, `body`.

| kind | meaning |
|---|---|
| `http` | non-2xx answer (not a handled 401) |
| `unauthorized` | HTTP 401 for a request that carried a session token |
| `unauthenticated` | no session; nothing was sent |
| `timeout`, `cancelled` | deadline, caller abort, or the user changed while the request ran |
| `network` | `fetch` failed (the original message is kept) |
| `malformed_response` | 2xx body that is not JSON |

An HTTP failure keeps the historical message `API request failed: <status> <body>`, so `getApiErrorMessage`,
`readApiFailure` and the screens that parse the message work unchanged. `code` is read only if the body has a
snake_case `code` string (BE-1 is not implemented yet, so it is `null` today). A mapper keyed by `code` is not part of
this task.

## Retry policy

GET only, at most **2 retries** (3 attempts), waits 300 ms then 900 ms, only for a network failure or HTTP
502/503/504, and only if the wait fits in the remaining deadline. Never retried: 401, 403, 404, 409, 422, 500, any
timeout or cancellation, and every POST/PATCH/PUT/DELETE and upload (exactly one network attempt). TanStack Query's own
retry is disabled (`createAppQueryClient`), so attempts are not multiplied. A request is never replayed after a 401 or
a token refresh.

## HTTP 401 and the session

1. The transport reports the identity (user id + access token) that was rejected.
2. `session-lifecycle.ts` ignores it unless that token is still the active session's token (a newer or different
   session is never signed out by an old 401).
3. Simultaneous 401s for one token share one check.
4. The check asks Supabase to refresh. A new token means the session lives (no sign-out; the failed request is not
   replayed). Only an explicit rejection by the auth server (`AuthApiError` 400/401/403/404/422, or no session) confirms
   the session is invalid, after a second "still the same session" check. Network errors, 5xx and 429 leave the session
   alone.
5. A confirmed-invalid session is ended with `signOut({ scope: "local" })`.

## Cache isolation

`SessionBoundary` counts epochs per signed-in user. The auth listener (and, as a safety net, every request) reports
the user. When a signed-in user is replaced or signs out:

1. the old epoch's requests are aborted, and a response that still arrives is refused by the transport (`cancelled`);
2. `SessionQueryClient` **retires** the current `QueryClient` (`clear()`, and its mutation callbacks are halted, see
   below) and installs a **new client** for the next user; `app/_layout.tsx` re-provides it (`useSyncExternalStore`).

A token refresh for the same user changes nothing. The first user after "nobody" is only adopted, because sign-out
already rotated the client.

### Mutation callbacks (MF2-SR01)

`useMutation` callbacks (`onSuccess`/`onError`/`onSettled`) belong to the mutation, not to the screen: they keep running
after the screen unmounted and after sign-out, and several screens write the cache or navigate in them (for example
`receipt-upload-screen.tsx` calls `setQueryData` and `router.push`; `goal-priorities-screen.tsx` writes
`["goals", userId]`). With one shared client such a callback could write user A's data into user B's cache (the receipt
key has no user id) and navigate B to A's screen. Protection, in two layers:

- **Retired clients halt their mutations.** The client's `MutationCache` hooks `onSuccess`/`onError`/`onSettled` never
  settle once the client is retired. TanStack awaits them *before* the screen's own callbacks, so none of the screen's
  callbacks run, whether the request finished after the switch or before it. A retired mutation never settles (a
  `mutateAsync` caller stays pending; its screen is gone) and is never replayed.
- **Callbacks already running hold the old client.** Screens get the client from `useQueryClient()` while rendering, so
  a callback body that was already past the hooks and resumes later writes and invalidates only the retired, cleared
  client: nothing reaches B's cache or fetches under B's session.

What this does not stop: an already-running callback body that resumes after an `await` and calls `router.push`/`back`.
The body must check `isCurrentQueryClient(queryClient)` (from `lib/session-runtime.ts`) before navigating or starting
new requests; `receipt-upload-screen.tsx` does this after its status check. Today's bodies only await HTTP calls, which
the transport aborts on a user change, so no other screen needs the check; new code must add it after any other await.

## Navigation intent

When the server invalidates a session, the last in-app path is kept (only plain `/segment/segment` paths: no query,
fragment, scheme, `..` or `/sign-in`), for 30 minutes, once, and only for the same user. A deliberate sign-out or a
different user discards it. `app/_layout.tsx` tracks the path and restores it with `router.replace`.

## Error presentation (audit)

Screens that show `error.message` in an alert: `receipt-upload-screen.tsx` (upload, process, picker and camera
failures), `goal-create-screen.tsx`, `budget-create-screen.tsx`, `budget-edit-screen.tsx`, `budgets-screen.tsx`
(delete), `categories-screen.tsx` (visibility), `dashboard-screen.tsx` (sign-out, a Supabase error) and
`app/sign-in.tsx` (Supabase). Other screens go through `getApiErrorMessage`, `getGoalErrorMessage` or a status-only check.

- `ApiError` does not change what these screens show for HTTP failures: the message is byte-for-byte the historical
  `API request failed: <status> <body>`. **That text, including the raw server body, was already shown by the screens
  above before MF-2** (a pre-existing presentation defect, not introduced here). `ApiError.body`, `status`, `detail`
  and `cause` are not rendered anywhere.
- New non-HTTP messages are fixed strings: `Request timed out.`, `Request was cancelled.`,
  `The server returned an unreadable response.`, `User is not authenticated.`; a network failure keeps the runtime's
  own message (`Network request failed`). Tests assert that no message or serialized field contains the access token,
  the base URL or the request path.
- Not changed in MF-2 (the exact messages are the compatibility contract of the existing mappers).

**Deferred requirement (after BE-1, `feat/VF-API-ERROR-CODES`):** codes do not exist yet, so none are mapped or
invented. Once the backend returns the stable snake_case `code` on every error body, add one user-facing mapper
`code -> copy` with a string fallback (using `ApiError.code`, `status` and `kind`), and replace every direct
`error.message` alert above with it, so a 5xx page or JSON body is never shown. Until then the unmapped screens above
can show technical text for HTTP errors. Unknown or missing codes must fall back to a neutral message, never the body.

## Known limits

- Services do not yet forward TanStack's `signal` into `apiRequest`; unmounted queries are not aborted on the
  network until MF-3.
- A retired mutation never settles, so any `await mutation.mutateAsync(...)` of a signed-out screen stays pending (the
  screen is unmounted; memory is released when the client is dropped).
- A callback body that resumes after an `await` other than HTTP must check `isCurrentQueryClient` before navigating.
- The route restore effect in `app/_layout.tsx`, the client rotation in a mounted React tree, and the real Supabase
  refresh-rejection behavior are covered by review and Node tests of the pure parts only; they need the staging/device
  drills (BR-7) before they can be called accepted.
