# Mobile authentication: sign-up, email confirmation, password recovery (VF-MOB-AUTH-REGISTRATION, MF-4)

Status: **implemented and verified locally with fake and scripted auth responses.** Nothing here has run against a Supabase
project, no email was sent or received, and no device or simulator was used. Real-service and device acceptance are listed
in section 8 and remain **NOT RUN**.

Scope: mobile only (`apps/mobile`). No backend, schema, financial-rule or deployment change. The finance API is not involved:
these flows are Supabase Auth client calls (`docs/mvp/api-mobile-contract-matrix.md`, "Supabase Auth").

## 1. Screens and routes

| Route | Screen | Reachable when |
|---|---|---|
| `/sign-in` | existing, plus "Forgot password?" and "Create account" links | signed out |
| `/sign-up` | email, password, confirm password | signed out |
| `/check-email` | "check your email" after sign-up, resend with a 60 s cooldown | signed out |
| `/forgot-password` | request a reset link; neutral confirmation | signed out |
| `/reset-password` | choose a new password (also "Cancel") | **only during a password recovery** |
| `(app)` | the data screens | signed in and **not** recovering |

`apps/mobile/app/_layout.tsx` has three `Stack.Protected` groups driven by `decideRootRoute`
(`src/features/auth/recovery-state.ts`): `signed-out`, `recovery`, `app` (plus a neutral `loading` state while authentication
initializes or a link is being verified). A recovery session is a real Supabase session, but it never opens the data
screens until the new password is set (journey J20); the Smart Rules evaluation host follows the same rule (`useAppUserId`).

## 2. The URL scheme (B9)

`app.json` `expo.scheme` is now **`valorfinis`** (was the generic `mobile`). The auth redirect URL is
`valorfinis://auth/callback` (`src/lib/auth-link-runtime.ts`, built from the scheme by `buildAuthRedirectUrl`).
`isAppSpecificScheme` rejects the generic values and a test pins the value in `app.json`.

The scheme is a **custom URL scheme**, so it is not exclusive to this app: another app can register the same one. It is
unique enough to avoid accidental clashes; it is not a secret. See "Residual risks".

Changing a scheme requires a native rebuild of any development or QA build (an OTA update cannot change it).

## 3. How a link reaches the app

```
OS opens valorfinis://auth/callback#...
  -> app/+native-intent.ts  (redirectSystemPath, before Expo Router)   claims the URL; the router sees "/" (cold start)
                                                                       or nothing (running app); the credential never
                                                                       becomes a route, a parameter or a history entry
  -> authLinkHandler.receive(url)   synchronous: parse, mark the recovery state "verifying" (neutral loading UI)
  -> AuthLinkHost                   drains the handler once authentication is initialized (and on every later link)
  -> guarded Supabase client        exchangeCodeForSession (queued with every other session change)
  -> SIGNED_IN event -> auth coordinator -> session boundary (unchanged)
  -> recovery state "active" for that user -> the navigator shows /reset-password
```

`detectSessionInUrl` stays `false`; the handler parses the link itself (`src/features/auth/auth-link.ts`).

**The client now uses the PKCE flow** (`flowType: "pkce"` in `src/lib/supabase.ts`) and **only PKCE links are applied**:

| Form | Example | Result |
|---|---|---|
| PKCE code | `?code=..` | `exchangeCodeForSession`; the exchange's redirect type (`"recovery"`, verified against auth-js 2.112.3) says if it was a password recovery |
| implicit tokens | `#access_token=..&refresh_token=..&type=recovery` | **refused** ("unsupported"), never applied |
| token hash | `?token_hash=..&type=recovery` | **refused** ("unsupported"), never applied |
| error | `#error=access_denied&error_code=otp_expired..` | "invalid or expired" notice, no auth call |

Why: a link that carries a ready-made session (or a one-time token hash) is not bound to the device that asked for it. An
attacker could create their own account, request a confirmation or reset email to their own mailbox and send the victim the
resulting link; the victim's app would silently switch to the attacker's account (login CSRF), and the victim would then type
financial data into it. A PKCE code is useless without the code verifier that only the requesting device stored, so a link
for a request made elsewhere fails with no session change (tested on the real auth-js). Password sign-in is unaffected by the
flow type.

Consequences: a confirmation or recovery link opened on a **different device** than the one that asked for it does not
sign that device in (it shows "invalid or expired"; for a confirmation the account is already confirmed, so signing in works);
only the newest request's link works (one verifier slot); and the app must have requested the email itself.

**Verifier strength is device-dependent (not verified):** auth-js uses SHA-256 challenges only if a WebCrypto `crypto.subtle`
exists and otherwise falls back to the `plain` method (with a console warning) and a non-cryptographic random verifier.
Whether Hermes in the Expo 57 build provides `crypto` was **not verified** (no device run). The login-CSRF protection holds in
both cases (the attacker cannot know the victim's verifier); only on-path observation of the verifier is weaker with `plain`.
If it falls back, add a `crypto.getRandomValues`/`subtle.digest` polyfill backed by `expo-crypto` (already a dependency).

## 4. Race and ownership rules

* **One queue.** Every call that can store a session (`signUp`, `setSession`, `exchangeCodeForSession`, `verifyOtp`,
  sign-in, sign-out) already runs in the auth operation queue through the guarded client. New: the password change
  (`createGuardedPasswordUpdate`, `api/auth-operations.ts`) and leaving a recovery (`endSessionIfOwned`, exported from
  `lib/session-runtime.ts`) run in the same queue and verify ownership **inside the slot** before acting. A recovery screen
  opened for user A can never change the password of, or sign out, user B who signed in meanwhile.
* **Newest link wins.** Every link attempt has a generation (`recovery-state.ts`); an older attempt that resolves late
  applies nothing and shows nothing. If it stored a recovery session that is still the current session, that session stays
  gated (`keepRecovery`).
* **A failed link never opens the gate.** A malformed, expired, refused or replayed link changes no recovery state at all.
  A new code attempt closes the gate only while it runs; if it fails, the recovery that was in force is restored, so a recovery
  session can never fall through to the data screens because of a later bad link.
* **Identity check.** After the session exists, the recovery is activated only if the authoritative current user (session
  boundary) is still that session's user.
* **A recovery belongs to one user.** The auth provider feeds every published session to `recovery.reconcile`; any other
  user, or nobody, ends the recovery. It never carries over to another account.
* **Cache isolation is unchanged.** A recovery for a different user than the signed-in one is an ordinary A -> B change at the
  session boundary: A's query client is retired and B starts empty. A recovery for the same user keeps the cache.
* **Replays.** The same URL delivered twice (initial URL plus event) is processed once. Opening a link again after it was
  used reports "invalid or expired" without calling the server. A link whose attempt could not reach the server is **not**
  marked used, so opening it again retries.
* **Restart safety.** See section 4.1.
* **Restored intent.** The saved location is restored only for the same user, once, and only in the `app` route (never during
  a recovery). Signed-out screens are never saved. Cancelling a recovery discards it.
* **No automatic retry** of any authentication call; one call per user action, double taps are absorbed by a synchronous
  submit guard.

### 4.1 Restart safety: a recovery session never survives a process kill as an app session

Reported defect: request a reset, open the link, reach the Reset Password screen, kill the app, relaunch; auth-js restores the
persisted recovery session and the in-memory recovery state is gone, so the data screens opened. Fixed as follows.

* **Durable record** (`recovery-persistence.ts`, AsyncStorage key `valorfinis.password-recovery.v1`, user ids only, never a
  token, code or email): `verifying {priorUserId, recoveryUserId}` is written and **awaited before every PKCE exchange** (if it
  cannot be written the exchange is not attempted); `active {userId}` records the recovery session after it is established.
* **Closed until resolved.** The app's recovery state starts in a `resolving` phase (`recovery-state.ts`). The root route is
  `loading` and the rules evaluation host receives no user while it is `resolving` or `verifying`; links wait for it
  (`auth-link-host.tsx`). The first settled authentication state goes to `createStartupResolver` **before** the session is handed
  to React (`auth-context.tsx`, `lib/auth-link-runtime.ts`).
* **Startup decision** (`recovery-startup.ts`, table in the file header), failing closed:
  `active U` + session `U` -> resume the reset screen; `active U` + no/other session -> record cleared; `verifying` + no session
  -> cleared; `verifying` + the recorded recovery user -> resumed; `verifying` + the unchanged prior user -> kept (the exchange did
  not replace the session); `verifying` + anybody else, or an unreadable/corrupt record with a session -> the session is **ended**
  locally through the guarded session end (ownership-checked, in the auth queue) and the record is cleared afterwards. If the
  session cannot be ended the reset screen (with Cancel) is shown, never the app.
* **Failed restore.** If the stored session could not be read (the restore reported an error), "no session" may only mean "not
  loaded yet". The state becomes `deferred`: signed out as far as the app knows, the record is kept, and the state is **sticky**: a
  link attempt that fails (or is offline) returns to `deferred`, never to `idle`, and the verifying record written before an
  exchange **accumulates** the earlier evidence (the recovery user id) instead of overwriting it. When a session appears, the
  gate is closed again synchronously (before it can render), also when that happens while a link attempt is running (it is
  judged the moment the attempt ends), and the decision is made then. A `deferred` state with a session is never the app.
* **A sign-out is only "done" when it is.** auth-js reports a failed local sign-out as `{ error }` (for example an expired stored
  session while the auth server is unreachable: nothing is removed). Cancelling a recovery and the startup resolution use
  `endSessionVerified` (`createVerifiedLocalSignOut`), which throws unless auth reports success **and** the session boundary shows
  nobody signed in. Cancel then reports "failed" (the reset screen stays, its record stays, with a retry message); startup falls back
  to the reset screen. The 401 flow keeps using the unchanged `endSessionIfOwned`.
* **Order is the safety argument.** The record outlives the session, never the other way round: cancelling signs the session out
  first and the record is removed when the recovery ends; a password change removes it after `updateUser` succeeded. A crash
  in between leaves a record without a session (cleared at startup) or the reset screen again (safe), never a session without a
  record.
* **Crash windows** covered by tests on the real auth-js: before the record is durable (no exchange), after the exchange but
  before the `active` record (unexplained session -> ended), during an exchange with no session stored, killed on the reset
  screen, after a password change, after cancel, between sign-out and record removal, user B signing in after a recovery.

Tests: `recovery-persistence.test.ts`, `recovery-startup.test.ts`, `recovery-state.test.ts` (resolving, reopen),
`auth-link-handler.test.ts` (record before exchange) and the restart section of `auth-recovery-integration.test.ts`, where a
process is "killed" (nothing durable is cleaned up) and a new one starts on the same storage, including a failed restore with a
late session, a failing link while deferred, and a sign-out that cannot complete. Each asserts that the recorded
route sequence never contains `app` (the only route in which data screens or Smart Rules evaluation exist).

Accepted limit: a recovery link opened by a user who is **already signed in as the same user** on that device is indistinguishable
from that user's ordinary session after a crash inside the exchange (the user already had full access, so nothing is escalated).
A storage failure that makes the record unreadable fails closed (any session is ended).

## 5. Non-enumeration (copy rule C6)

Messages are chosen from the *class* of the failure (`auth-errors.ts`, by `error.code`/`name`/`status`), never from the
server's text, so no message can reveal account state or carry a credential.

| Flow | Outcome for a new address | Outcome for an existing address |
|---|---|---|
| sign-up, confirmation required | "check your email" | the same (success-without-session or `user_already_exists`/`email_exists`) |
| forgot password | "if an account can use <address> we sent a link" | the same, and the same for an unknown address |
| resend confirmation | the same neutral message | the same |

Not hideable by any client: **if the project does not require email confirmation**, a new address is signed in immediately and
an existing one is not. That depends on the Supabase settings (checklist A-02, A-07) and is to be recorded there.

The existing sign-in screen is unchanged (it still shows the auth service's credential message).

## 6. Password rules

The client checks only a floor (8 to 72 characters, matching confirmation). The project's real policy (checklist A-04) is
enforced by Supabase; its rejection (`weak_password`, with reasons) is shown with fixed wording. A lost answer on the password
change is reported as "could not confirm" (never as success or failure) and the user may submit again.

## 7. Tests (all fake or scripted, no network)

`src/features/auth/`: `auth-link.test.ts` (forms, errors, malformed, unsupported, scheme), `auth-link-handler.test.ts`
(cold start, running app, duplicates, replay, expired, refused implicit/token-hash links, concurrent links, a failed link never
releasing a recovery, identity change, secrets),
`recovery-state.test.ts` (generation, ownership, root route), `auth-errors.test.ts`, `auth-registration.test.ts`
(sign-up, confirmation on/off, existing email, reset, resend, rapid submissions), `password-recovery.test.ts`,
`native-intent.test.ts`, `auth-mf4-structure.test.ts` (no logging, no raw error text, layering, guard groups, restored intent),
and `auth-recovery-integration.test.ts`, which runs the **real `@supabase/auth-js`** behind the app's real queue, gateway,
session boundary, coordinator, recovery state and link handler against a scripted GoTrue server (recovery session, expired and
rejected links, replay, login CSRF with a code from another request, user B signing in during a recovery, sign-out during a
recovery, junk links during a recovery, cache reset counts).

## 8. NOT done here: hosted configuration and device acceptance

Hosted Supabase configuration (not done; this repository configures nothing remotely):

1. Add `valorfinis://auth/callback` to the **staging** project's redirect URL allowlist (checklist A-05): exact entry, no
   wildcard, no production URL. Never to production until MF-4 is accepted on staging.
2. Record A-02 (confirmation on/off), A-03 (SMTP sender), A-04 (password policy), A-06 (rate limits), A-07 (observed existing-
   address and unknown-address responses) and A-08 (the actual link form). Confirm the email templates use `{{ .ConfirmationURL }}`
   (or the token-hash form) and that the link reaches the redirect URL.
3. Confirm the project issues PKCE links (`?code=`) to the app: it does when the request carries a code challenge, which the
   client now always sends. The email templates must use `{{ .ConfirmationURL }}`; a template that builds a token-hash link
   would be refused by the app.

Real-device acceptance (journeys J19 and J20, both platforms, **NOT RUN**): register -> (confirm) -> sign in; second
registration with the same address shows the neutral screen; request a reset -> open the emailed link on the device (cold
start and app running) -> set the password -> signed in; expired link; reused link; link opened on another device; a link
for a different account while signed in; Android/iOS handling of the custom scheme; screen reader and keyboard behavior of
the four new screens; rate-limit behavior.

## 9. Residual risks and decisions for the owner

* **Custom scheme interception (Android especially).** Any app can register `valorfinis://`. With PKCE the link carries only a
  code that is useless without the verifier stored by this app, so an app that wins the scheme cannot use it. Verified
  App/Universal Links need a hosted domain and are out of scope here.
* **Verifier strength** depends on WebCrypto being present at runtime (section 3). Unverified.
* **The password change does not revoke the user's other sessions.** Add `signOut({ scope: "others" })` after a successful change
  if the owner wants that.
* **Redirect URL environment.** The scheme is the same for every environment; staging and production are separated by
  their Supabase projects and allowlists, not by scheme.
* Sign-in still shows the auth service's own message for a failed login (existing behavior, outside this task).
