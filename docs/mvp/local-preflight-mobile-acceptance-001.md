# MOBILE-ACCEPTANCE-001 — Local Runtime Preflight (not official acceptance)

Date: 2026-11-13. Repository commit: `main` @ `d46781d246f6fa334be59f4a582190b62561d989`. Branch `qa/VF-MVP-MOBILE-ACCEPTANCE-001`.

**Scope and status.** This is a *local preflight* on the developer's machine. It is **not** the official staging or
physical-device acceptance of [qa-device-matrix.md](qa-device-matrix.md) and
[qa-evidence-and-staging-isolation.md](qa-evidence-and-staging-isolation.md) (principle 5: a simulator is supporting
evidence, never the physical-device PASS that BR-5 requires). No official `PASS` row is created or implied here.
No production, hosted Supabase, Render or remote database was contacted. No credential was used or printed; the three
`EXPO_PUBLIC_*` variables were set to local placeholders that point at no running service.

## 1. Environment readiness

| Item | Found | Assessment |
|---|---|---|
| macOS | 15.6.1 (24G90), arm64 | OK |
| Node.js | 22.23.2 (active, nvm); `apps/mobile/.nvmrc` = 22.13.0; `engines` `>=22.13.0` | Meets `engines`. The exact `.nvmrc` version 22.13.0 is not installed (only 20.19.2 and 22.23.2) |
| `npm ci` (apps/mobile) | 847 packages, exit 0, lockfile untouched | OK |
| Expo / RN | expo 57.0.20, react-native 0.86.3, expo-router 57.0.19 | OK. Expo CLI reports 57.0.33 is available (informational) |
| Xcode | 26.3 (17C529) | **Below the 26.4 that the Expo SDK 57 docs list as minimum** (already recorded as F-02 in the device matrix). Irrelevant to Expo Go; blocks a native development build |
| iOS Simulator runtime | iOS 26.3 (26.3.1) only | OK for Expo Go. The pinned iOS floor 16.4 cannot be tested here (no older runtime) |
| Simulator devices | iPhone 17 / 17 Pro / 17 Pro Max / Air / 16e; iPad (A16), Air, Pro, mini | All large screens. No small-phone device (smallest is iPhone 16e) |
| Expo Go | **Installed** on iPhone 17: bundle `host.exp.Exponent`, build 57.0.9 | Matches SDK 57. Nothing was installed or changed |
| Development build | None. No `ios/` or `android/` directory | Not available |
| CocoaPods | Not installed (`pod` not on PATH; system Ruby 2.6.10) | Blocks any native iOS build |
| Android | No `ANDROID_HOME`, no `~/Library/Android/sdk`, no `adb`/`emulator`/`sdkmanager`, no Java runtime | **BLOCKED** |
| Physical device | `xctrace list devices`: only this Mac; `devicectl`: none | **NOT RUN** |
| Docker | Present. Images include `postgres:16-alpine`, `axllent/mailpit`; **no** Supabase/GoTrue image | No local auth server available |

## 2. Authentication and API connectivity (the end-to-end blocker)

Findings from reading the code (not from guessing):

1. The app signs in with `supabase-js` against `EXPO_PUBLIC_SUPABASE_URL` and always calls FastAPI with
   `Authorization: Bearer <Supabase access token>` (`src/api/api-client.ts`). It never sends `X-User-Id`.
2. `get_current_user` (`services/api/app/modules/auth/auth_dependencies.py`) checks `Authorization` **first**. When a bearer
   token is present it is validated by calling `${SUPABASE_URL}/auth/v1/user` — **even when `AUTH_MODE=development`**.
   `X-User-Id` is honoured only when no `Authorization` header is sent.
3. Therefore the app **cannot** use the FastAPI development mode on its own. A working local end-to-end path needs
   something that answers Supabase Auth (`/auth/v1/token`, `/auth/v1/user`, signup/recover). None exists on this machine.

I did **not** add an auth bypass, did not weaken the backend, and did not build a fake identity provider.

**Smallest safe setup (owner action, needs approval):** a *local, disposable* Supabase Auth (GoTrue) instance, e.g. the
Supabase CLI local stack or a single `supabase/gotrue` container backed by a throwaway Postgres, with email confirmation
routed to the already-present Mailpit; FastAPI run with `AUTH_MODE=supabase`, `SUPABASE_URL` pointing at it and a
throwaway `valor_core`-style database; the app built with `EXPO_PUBLIC_API_URL`/`EXPO_PUBLIC_SUPABASE_URL` set to the
Mac's address (a physical phone cannot use `127.0.0.1`). This needs a Docker image download and a Supabase publishable
key generated for that local instance; neither was done.

## 3. Startup and simulator result (iPhone 17, iOS 26.3, Expo Go 57.0.9)

| Check | Result |
|---|---|
| Metro bundle | **PASS.** `iOS Bundled 7793ms node_modules/expo-router/entry.js (1613 modules)`, no errors |
| Missing env | App refuses to start without the three variables (`src/config/env.ts` throws). With placeholders it starts |
| Splash, navigation init | Reached `/sign-in` with no crash or red screen |
| Auth gate | Signed out: sign-in screen shown |
| Fonts / assets | No missing-asset error in Metro or on screen |
| Runtime warnings | One: `SafeAreaView has been deprecated` (see D2) |
| App background / foreground | Home, then relaunch: same screen and state, no crash |

Local tooling note (not an app defect): `expo start --localhost` on Node 22 bound Metro to IPv6 `[::1]` only while the
simulator requested `127.0.0.1`, giving "Could not connect to development server". Starting Metro in default mode with
`REACT_NATIVE_PACKAGER_HOSTNAME=127.0.0.1` listened on `*:8081` and worked.

## 4. Journey matrix

All authenticated journeys are **BLOCKED** by section 2. Statuses are only what was actually exercised.

| ID | Journey | Status | What was actually done / why |
|---|---|---|---|
| J01 | Sign in, restore session, sign out | **PARTIAL — BLOCKED** | Sign-in screen renders. Empty submit shows "Missing data / Enter your email and password." (PASS). Fake credentials with an unreachable auth host show "Login failed / Unable to reach the sign-in service. Check your connection and try again." (PASS, user-safe message). Password is masked (PASS). Sign-in success, restore and sign-out: **BLOCKED** |
| Registration | Create account screen | PARTIAL | Screen renders with Email, Password, Confirm password; link back to sign-in works. Submission **BLOCKED** (no auth server) |
| Password recovery | Reset password screen | PARTIAL | Screen renders; reached from "Forgot password?". Sending the link **BLOCKED** |
| Navigation | sign-in → create account → back; sign-in → reset password | PASS (signed-out screens only) | Exercised |
| J02–J12 | Accounts, Income, Expenses, Budgets, Goals, Transfers, Receipt, Dashboard/Overview/Analytics | **BLOCKED** | Not run: no authenticated session. (Their backend and service-level behavior is covered by the CORE-001…006 journey tests and the Node live harness, which are **not** simulator evidence) |
| J13–J18 | Financial Rules / Inbox | **NOT RUN** | The routes exist under `app/(app)/rules` and `inbox`, but `mvp-user-journeys.md` lists these journeys as mobile-NOT POSSIBLE/PARTIAL; not assumed |

Mobile-specific risks:

| Risk | Status |
|---|---|
| Real screen rendering (auth screens) | PASS |
| Input focus and text entry | PASS (first tap on a field right after a system dialog did not focus; see note) |
| Keyboard behavior | NOT RUN: the simulator used the hardware keyboard, no software keyboard was shown, so keyboard-avoidance is untested |
| Double tap on submit, form submission with data | NOT RUN (needs a reachable backend) |
| Back navigation | PASS (auth stack only) |
| React Query updates after navigation, loading/error states of data screens | BLOCKED |
| Camera / photo-library permission, native receipt upload via Expo `File`/`FormData` | **NOT RUN** (needs a session and, for the camera, a device) |
| App background/foreground | PASS (signed-out screen only) |
| Session persistence, user switching | BLOCKED |
| Small-screen layout, scrolling/hidden controls | NOT RUN (no small device available; auth screens are short) |
| Network interruption | PARTIAL: unreachable auth host handled with a clear message; data screens BLOCKED |
| Signed-out deep link to a protected route | **INCONCLUSIVE**: `exp://127.0.0.1:8081/--/accounts` left the screen unchanged; this is not recorded as a PASS |

Note on test mechanics: after dismissing an alert or the iOS "Save password?" system prompt, the next tap was
sometimes consumed by that overlay. This was the simulator and iOS system UI, not the app.

## 5. Defects and observations

No application defect was reproduced, so **no source change was made**.

| ID | Type | Detail |
|---|---|---|
| D1 | Observation (tooling) | Metro bound to `[::1]` with `--localhost` on Node 22 (see section 3). Use default LAN mode |
| D2 | Maintenance risk, not a failure | 24 files under `app/` and `src/` import `SafeAreaView` from `react-native` (13 others already use `react-native-safe-area-context`); RN 0.86 deprecates the former ("will be removed in a future release"). It renders correctly today. The replacement is `react-native-safe-area-context`, which the app already depends on. Not changed, because it is not a reproduced defect and would touch 24 files |
| D3 | Observation | Xcode 26.3 is below the documented Expo SDK 57 minimum 26.4 (known F-02); iOS 16.4 floor and Android untestable here |

## 6. Required owner actions

1. Approve and provide a local disposable Supabase Auth stack (section 2), or the QA-1 staging environment, so J01–J12 can run.
2. For Android: install a JDK and the Android SDK/emulator (not done; system-wide install needs approval).
3. For a native development build: Xcode 26.4+ and CocoaPods.
4. For BR-5: approve a physical reference device and run the official acceptance template against QA-1 staging.
5. Decide whether to schedule the `SafeAreaView` migration (D2).

## 7. Test results

Production source files were not changed, so the mobile suite, `tsc`, `lint` and backend tests were not re-run for this
slice. `npm ci` and the Expo bundle completed without errors. `git diff --check` is clean.
