# OPS-03 and Staging Prerequisites (VF-MVP-ENG-003)

Date: 2026-10-27. Produced offline. No production, Render or Supabase system was accessed; nothing here has been
executed. Anything about a deployed system is UNKNOWN until verified by the operator.

## 1. OPS-03: release security corrections

### 1.1 What is open (from [mvp-ops-dependencies.md](mvp-ops-dependencies.md))

| ID | Severity | Open on `main` because | Correction that exists | Still required |
|---|---|---|---|---|
| S1 | HIGH | E9A/E10 runbooks contain a hand-typed `alembic upgrade`; no `run_guarded_migration.sh` on `main` | Local commit `c4fbd73fadd9bfec24ec83071afb8de5c2d24ea4` (on local branch `docs/VF-020E10-OPS02-release-verification`, one commit ahead of the remote, **not on `main`**) | New branch from `main`, re-apply, full suite, independent review, authorized push + PR, green CI, user merge |
| S2 | MEDIUM | Gate H stage 1 claims connectivity a disabled dispatcher cannot prove | Same commit (stage 1 = smoke test; stage 1b = read-only runtime check) | Same path; Render Docker Command quoting for stage 1b verified on first deployment (UNKNOWN) |

They stay **release blockers** until merged with evidence. Local test results on the correction branch are
supporting evidence, not closure.

### 1.2 OPS3-1 procedure (for the task, not executed here)

1. `git switch main && git pull --ff-only`; confirm clean; `git switch -c fix/VF-OPS03-release-security-corrections`.
2. `git cherry-pick c4fbd73` (the commit is a single logical change; conflicts only if `main` changed those files).
   Rebase is forbidden by CLAUDE.md.
3. Verify: the guarded runner is mode 755; both runbooks contain no hand-typed `alembic upgrade` outside the runner
   documentation; run the release-verification tests and the full backend suite against `valor_test`
   (`DATABASE_URL=…/valor_test`), `alembic heads` = single head, `git diff --check`.
4. Independent security review (fresh context) of the diff; fix HIGH/MEDIUM; repeat the delta review.
5. Stop with `READY TO PUSH`. After explicit authorization: push, PR, wait for CI, user merges.
6. Then OPS3-2 (documentation truth) as its own branch.

### 1.3 Gate sequence after OPS3-1 (each separately authorized by the owner; none authorized here)

A diagnostics (read-only) → B E9A backup and restore proof → C E9A migration through the guarded runner → D
post-check and application validation → E E10 preflight and backup → F E10 migration through the guarded runner →
G post-check, role security, runtime compatibility → H Cron pricing, configuration, staged activation (stage 1,
then 1b) → I observed scheduled run. Gate H and I are needed only for an unattended claim (copy rule C1). Alert
rules in production need Gates C–D at minimum (E9A).

### 1.4 Separation rule

OPS tasks change only `docs/operations/**` and their tests. They must not carry mobile, API or feature changes,
and feature branches must not carry release corrections.

## 2. Staging prerequisites

Staging exists to run device acceptance, registration/recovery drills, the rules end-to-end scenario and
performance baselines **without touching production**. It is a separate environment end to end.

### 2.1 What must exist (owner inputs marked **[owner]**)

| # | Component | Requirement |
|---|---|---|
| 1 | Supabase project (staging) **[owner]** | Separate from production: its own URL, publishable key, Auth users. Never shares keys with production |
| 2 | Auth settings on that project **[owner/QA-1]** | Email confirmation setting recorded (on/off); SMTP for confirmation and recovery emails; redirect URL allowlist containing the app's unique scheme; password policy recorded; rate limits recorded; behavior for sign-up with an existing email observed and recorded (supports copy rule C6). **All currently UNKNOWN** |
| 3 | PostgreSQL for the API **[owner]** | Separate database, PG17 preferred (production engine major per ops notes), name ending `_staging` |
| 4 | Backend instance **[owner]** | Own deployment or local container pointed at the staging DB; `AUTH_MODE` set to the Supabase mode (not development); staging Supabase URL/key; receipt storage separate from production |
| 5 | Migration | Applied with the **guarded runner** (after OPS3-1) so the runner is rehearsed on staging before production |
| 6 | Data API hardening parity | The read-only OPS SQL checks (role privileges revoked for the Data API roles) pass on staging |
| 7 | Seed and reset (QA-1) | Scripts create named test users, Accounts, Goals, Budgets, rules; no real data. Reset drops/recreates only a database whose name ends `_test` or `_staging` (guard tested). Seeds contain no secrets |
| 8 | Mobile build channel | Environment variables `EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` point only at staging; the build used for QA cannot reach production |
| 9 | URL scheme | `apps/mobile/app.json` currently has the generic scheme `mobile`; an app-unique scheme is required before recovery deep links are enabled (task MF-4) |
| 10 | Devices | At least one physical iOS and one physical Android device; simulators/emulators at the floors (iOS 15.1, API 24) per QA-0 |
| 11 | Dispatcher rehearsal | Local run of `python -m app.modules.financial_rules.dispatcher` against the staging or disposable DB only |

### 2.2 Security rules for staging

- No production credential, URL or data appears in any staging configuration, seed, script or document.
- Secret values are never committed or printed; documents list variable **names** only.
- Test users use addresses the team controls; no customer data is copied to staging.
- Staging resets are routine; staging results are not used to claim anything about production.
- Registration/recovery drills record which Supabase settings were active, since results depend on them.

### 2.3 Facts that shape staging (verified in source)

- The backend validates every request by calling the Supabase `GET /auth/v1/user` endpoint with a 5-second timeout
  (`auth_dependencies.py`): staging API availability depends on that staging Supabase project being reachable, and
  an outage of it looks like a 401/5xx to the client. MF-2 timeouts and the BR-7 drills must cover this.
- The mobile Supabase client has `autoRefreshToken: true`, `persistSession: true` with AsyncStorage and
  `detectSessionInUrl: false`: recovery links must be handled explicitly by the app.
- New users need no backend provisioning: default categories are ensured lazily by the existing service.

### 2.4 Exit criteria for QA-1 (staging ready)

Staging migrated to head by the guarded runner; OPS SQL checks PASS; seed and reset work and the reset name guard has a
negative test; Auth settings recorded in the runbook; one end-to-end sign-in from a device build works against
staging only; a scan shows no production identifiers in the repository's staging configuration.
