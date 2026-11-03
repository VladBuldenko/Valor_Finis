# Staging Supabase Auth Settings Checklist (VF-QA-1, for MF-4)

Applies to the **staging** Supabase project only. Nothing below has been configured or observed: every "Recorded value" is empty
and every status is `NOT RUN` as of 2026-11-03. MF-4 (sign-up, email confirmation, recovery) must not start until this checklist is
filled by the owner and the QA-1 operator, because drill results depend on these settings (OPS03 section 2.2).

The mobile app currently uses the generic URL scheme `mobile`. The unique, production-appropriate scheme and the recovery screens
belong to MF-4. **QA-1 must not enable a recovery redirect**: leave the redirect allowlist without any app-scheme entry until MF-4
chooses the scheme (item A-05).

| ID | Setting | Why it matters | Recorded value | Status |
|---|---|---|---|---|
| A-01 | Email sign-up enabled | J19 registration | | NOT RUN |
| A-02 | Email confirmation required (on or off) | Decides the confirmation-pending state in MF-4 and what sign-up returns | | NOT RUN |
| A-03 | SMTP provider and sender (own staging sender, no production credentials) | Confirmation and recovery mail must arrive, and the built-in sender has a very low hourly limit | | NOT RUN |
| A-04 | Password policy (minimum length and character rules) | The app's validation copy must match what the server enforces | | NOT RUN |
| A-05 | Redirect URL allowlist and site URL | A recovery link may only return to an entry listed here. No wildcard, no production URL, no generic `mobile://`. Empty of app-scheme entries during QA-1 | | NOT RUN |
| A-06 | Rate limits (emails per hour, sign-ins, token refreshes, OTP) | Drills J19/J20 and BR-7 must not be blocked by, or mistaken for, a limit | | NOT RUN |
| A-07 | Account enumeration behaviour: response to sign-up with an existing address, and to recovery for an unknown address | Copy rule C6 requires identical, non-revealing messages; record the observed responses with A-02 active | | NOT RUN |
| A-08 | Password recovery callback: form of the link (token in the fragment, query, or a PKCE code) and the page it opens | The app has `detectSessionInUrl: false`, so MF-4 must parse the link itself; the form decides how | | NOT RUN |
| A-09 | Token and session settings: access-token lifetime, refresh-token rotation and reuse interval | BR-7 expiry drills; `autoRefreshToken` and `persistSession` are on in the app | | NOT RUN |
| A-10 | CAPTCHA or bot protection enabled | Would block automated and scripted drills | | NOT RUN |
| A-11 | Leaked-password protection available and enabled | Affects which test passwords are accepted | | NOT RUN |
| A-12 | Other sign-in providers disabled | Smaller attack surface; MVP uses email and password | | NOT RUN |
| A-13 | Data API exposure of the `public` schema; role privileges for `anon`, `authenticated`, `service_role` | Parity with production hardening (migration `edcfdf3f7114`); the read-only OPS SQL checks verify it | | NOT RUN |
| A-14 | Auth users QA-A and QA-B created, addresses team-controlled, ids recorded outside the repository | The seed maps actors to these ids | | BLOCKED |

## Facts MF-4 needs from QA-1

| # | Fact | Source |
|---|---|---|
| F1 | Staging Supabase URL and publishable key exist (names only here) and the live probe passes | `staging_ops` Supabase probe, [configuration](backend-and-mobile-configuration.md) |
| F2 | Email confirmation on or off | A-02 |
| F3 | A confirmation and a recovery email were actually received | A-03 |
| F4 | Password policy values | A-04 |
| F5 | Rate limits | A-06 |
| F6 | Redirect allowlist is empty of app-scheme entries, and the unique scheme still has to be chosen | A-05, `apps/mobile/app.json` |
| F7 | Observed sign-up-with-existing-address and recovery-unknown-address responses | A-07 |
| F8 | Form of the recovery link | A-08 |
| F9 | Session and token settings | A-09 |
| F10 | QA-A and QA-B exist and the seed has run | A-14, [runbook R7 and R8](staging-architecture-and-runbook.md#6-runbook-operational-not-executed-by-qa-1) |
| F11 | The API treats a Supabase outage as 401 or 5xx (it validates every request against `/auth/v1/user` with a 5-second timeout); MF-2 and BR-7 drills must cover it | OPS03 section 2.3 |

Registration and recovery drills record which of these settings were active when they ran.
