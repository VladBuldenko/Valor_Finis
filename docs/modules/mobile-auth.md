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
* **Restored intent.** The saved location is restored only for the same user, once, and only in the `app` route (never during
  a recovery). Signed-out screens are never saved. Cancelling a recovery discards it.
* **No automatic retry** of any authentication call; one call per user action, double taps are absorbed by a synchronous
  submit guard.

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
* **Killing the app on the reset screen** leaves the recovery session stored, so the next start opens the app as that user
  with the old password unchanged. This equals what the user proved (control of the mailbox) but is not what J20 describes;
  "Cancel" ends the session on this device. A persisted recovery marker would close it and was left out of scope.
* **The password change does not revoke the user's other sessions.** Add `signOut({ scope: "others" })` after a successful change
  if the owner wants that.
* **Redirect URL environment.** The scheme is the same for every environment; staging and production are separated by
  their Supabase projects and allowlists, not by scheme.
* Sign-in still shows the auth service's own message for a failed login (existing behavior, outside this task).
