# Mobile API client (VF-MF-2)

Scope: `apps/mobile/src/api`, `src/lib` (`session-*`, `query-client.ts`), `src/features/auth` (`auth-coordinator.ts`, `navigation-intent.ts`), `app/_layout.tsx`.
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

## Session ownership (MF2-SR02, SR06)

A request must never decide who is signed in. `SessionBoundary` is changed only by **authoritative** events:
`AuthProvider` feeds Supabase's `onAuthStateChange` and the initial `getSession()` restore through
`auth-coordinator.ts`, which calls `boundary.applyAuthEvent(userId)` BEFORE the UI is told.

- Every identity change (nobody -> A, A -> B, A -> nobody, B -> A) advances an **epoch**; a same-user token refresh
  does not. Leaving a signed-in user aborts that epoch's requests and retires its query client.
- A request takes a snapshot (epoch + the user it belongs to) **before** its asynchronous `getSession()`. Afterwards it
  must still be in the live epoch and the lookup must name the snapshot's user, else it is refused (`cancelled`)
  before any HTTP. The epoch is re-checked before every dispatch (also after retry waits) and when the body has been
  read. Comparing user ids alone would let a request of the first "A" generation become valid after A -> B -> A.
- A request never calls `applyAuthEvent`. Earlier (ef9b63b) it did, so a delayed `getSession()` of A could turn B back
  into A: B's request was cancelled, A's obsolete token was sent, and the client was rotated twice. A session the
  coordinator has not adopted (a missed or late event) is refused, not adopted.
- The initial restore compares an event counter taken before its await; if any auth event arrived meanwhile (a login,
  or a sign-out during restoration) the restore result is discarded. The event handler is synchronous and makes no
  Supabase Auth call (supabase-js can deadlock on re-entrant auth calls inside the callback).

## Cache isolation and the session subtree

When a signed-in user is replaced or signs out, `SessionQueryClient` **retires** the current `QueryClient` and
installs a **new** one. `app/_layout.tsx` renders `AuthProvider` (stable, outermost) and inside it `SessionScope`
(`lib/session-scope.ts`): a `QueryClientProvider` **keyed by the client generation**. TanStack creates each hook's
`QueryObserver`/`MutationObserver` once per component instance and does not rebind it when the provider's `client`
prop changes, so without the key B's screens would keep observers attached to A's retired client (B's mutation then
never settles; reproduced in `session-scope.test.ts`). With the key React unmounts the whole authenticated subtree and
mounts new components, so A's observers are never reused for B, and A -> B -> A is a new logical session. A token
refresh does not rotate, so it does not remount.

### Mutation callbacks (MF2-SR01)

`useMutation` callbacks (`onSuccess`/`onError`/`onSettled`) belong to the mutation, not to the screen: they keep running
after the screen unmounted and after sign-out, and several screens write the cache or navigate in them (for example
`receipt-upload-screen.tsx` calls `setQueryData` and `router.push`; `goal-priorities-screen.tsx` writes
`["goals", userId]`). A retired client therefore:

- **never starts a new mutation** (`onMutate` hook halts before `mutationFn` runs: no request under the next user's
  token);
- **never reaches a screen callback** of a running mutation (`onSuccess`/`onError`/`onSettled` hooks never settle;
  TanStack awaits them before the screen's own callbacks);
- **has inert queries** (`queryFn` is replaced by a `cancelled` rejection: no request, nothing stored);
- **holds the callbacks that were already running** (they captured the retired client while rendering), so a body that
  resumes later writes only into a cleared, dead cache.

What this does not stop: an already-running callback body that resumes after an `await` and calls `router.push`/`back`.
Such a body must check `isCurrentQueryClient(queryClient)` (`lib/session-runtime.ts`) before navigating or starting new
requests; `receipt-upload-screen.tsx` does after its status check. Today's other bodies only await HTTP calls, which the
transport aborts on a user change; new code must add the check after any other await.

### Resource ownership of retired mutations (MF2-SR05)

"Never settle" is intentional: settling would run the screen's callbacks. A halted mutation is a suspended
`Mutation.execute()` awaiting a promise nothing else references. The retired client was removed from every registry
(`SessionQueryClient` keeps only the live one; `clear()` drops its caches), so nothing reachable from a root points at
the suspended frames, the client, the observers, or the callback closures. `retired-client-lifecycle.test.ts` measures
this: 25 account changes with a pending mutation each (every closure holding 1 MiB) end with **0 retained clients, 0
retained closures** after a forced collection (WeakRef), heap growth below 8 MiB, and a negative control (retaining the
retired clients) makes the test fail. Limits that remain: a `mutateAsync`/`await` of a signed-out screen stays pending
until it is collected with its screen (never resolved or rejected), no unhandled rejection is created, and the
evidence is a Node/V8 measurement, not a Hermes device measurement.

## Navigation intent

When the server invalidates a session, the last in-app path is kept (only plain `/segment/segment` paths: no query,
fragment, scheme, `..` or `/sign-in`), for 30 minutes, once, and only for the same user. A deliberate sign-out or a
different user discards it. `app/_layout.tsx` tracks the path and restores it with `router.replace`.

## Error presentation (MF2-SR04)

`error.message` of an HTTP failure stays the historical `API request failed: <status> <raw body>` (the parsing helpers
depend on it) and can contain HTML, stack traces or JSON envelopes, so **screens must not show it**.
`api/user-facing-error.ts` is the presenter:

- `getUserFacingErrorMessage(error, fallback)` works for the typed `ApiError` and a legacy wrapped `Error`
  identically. 5xx: never the body or detail (502/503/504: "temporarily unavailable"; others: a neutral server
  message). 401/403: fixed texts. Other 4xx (409, 422, 404, ...): the backend's string `detail` or first validation
  `msg` if it is at most 300 characters and not technical (traceback, markup, SQL, driver names, JSON), else the
  fallback. Network, timeout, cancelled, unreadable response, no session: fixed texts (the runtime's exception text,
  URL, path and token are never shown). Anything unrecognised: the fallback.
- `getAuthErrorMessage(error, fallback)` for Supabase Auth: an `AuthApiError` message (for example "Invalid login
  credentials"), a fixed text for `AuthRetryableFetchError`, else the fallback.
- `getApiErrorMessage` and `getGoalErrorMessage` additionally never return a 5xx body or detail (and the goal mapper no
  longer returns a raw wrapper for a non-JSON 4xx body). `readApiFailure` and `ApiError` still expose `status`, `detail`,
  `kind`, `code` and `body` to application logic.
- The 11 direct alert sites were switched: receipt-upload (upload, process, picker, camera), goal-create,
  budget-create, budget-edit, budgets (delete), categories (visibility), dashboard (sign-out) and sign-in.

**Remaining:** a non-API `Error` passed to `getApiErrorMessage`/`getGoalErrorMessage` still returns its own message
(existing contract, covered by existing tests); other screens' own mappers were not audited line by line beyond a grep
for `.message`. **Deferred requirement (after BE-1, `feat/VF-API-ERROR-CODES`):** no code is mapped or invented. When
the backend returns a stable snake_case `code` on every error body, extend the presenter with a `code -> copy` table
(using `ApiError.code`, `status`, `kind`) and a neutral fallback for unknown or missing codes, so copy no longer depends
on parsing `detail`.

## Known limits

- Mounted-React evidence uses `react-test-renderer` (devDependency, deprecated upstream but the only DOM-free option)
  with the real TanStack hooks and the real `SessionScope`/boundary/transport, and a scripted `AuthGate`. It does not
  cover `AuthProvider`, Supabase, Expo Router, `Stack.Protected` or the navigation-intent restore effect; those need the
  staging/device drills (BR-7), which are NOT done.
- Services do not yet forward TanStack's `signal` into `apiRequest`; unmounted queries are not aborted on the network
  until MF-3.
- A callback body that resumes after a non-HTTP `await` must check `isCurrentQueryClient` before navigating.
- A session that `getSession()` returns but the coordinator has not adopted (a lost or late auth event) is refused
  until the event arrives; there is no request-side recovery, by design.
- `ApiError.code` is `null` until BE-1. Retry waits are fixed (no jitter).
- The package change of MF-2 R2 (`react-test-renderer`, `@types/react-test-renderer` as exact devDependencies) will
  conflict textually with the owner's local `package.json`/`package-lock.json` edits; merge those after this branch
  and regenerate the lockfile.
