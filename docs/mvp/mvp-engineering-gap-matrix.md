# MVP Engineering Gap Matrix (VF-MVP-ENG-003)

Date: 2026-10-27. Scope: [mvp-scope-v1.1.md](mvp-scope-v1.1.md). Evidence: [mvp-repository-audit.md](mvp-repository-audit.md),
[api-mobile-contract-matrix.md](api-mobile-contract-matrix.md), [mvp-qa-readiness.md](mvp-qa-readiness.md).

Columns: **Req** = scope requirement; **WS** = workstream (OPS, MF mobile foundation, BE backend, F VF-020F rules
mobile, QA, DOC); **Task** = closing task in [mvp-engineering-qa-roadmap.md](mvp-engineering-qa-roadmap.md);
**Closure test** = the measurable proof. A gap is closed only when its closure test has stored evidence.
"Open P0" counts feed gate BR-1.

## 1. Gaps

| Gap | Description (evidence) | Req | Pri | WS | Depends on | Task | Closure test |
|---|---|---|---|---|---|---|---|
| GAP-01 | E9A/E10 runbooks use a hand-typed `alembic upgrade` on `main` (`e9a-production-migration.md:140`, `e10-production-migration.md:55`); runner exists only in local `c4fbd73` | S1 | **P0** | OPS | none | OPS3-1 | `run_guarded_migration.sh` on `main`; runbooks contain no hand-typed upgrade (grep = 0); negative tests green; CI green; user merged |
| GAP-02 | Gate H stage 1 claims connectivity it cannot prove (`financial-rules-production-release.md` §11) | S2 | **P0** | OPS | GAP-01 | OPS3-1 | Stage 1 text is smoke-only; stage 1b read-only check present and tested |
| GAP-03 | Stale release/roadmap docs (audit D1–D8, ops R3–R7) | — | P1 | DOC | none | OPS3-2 / DOC-1 | Zero statements contradicting `git log`/`alembic heads` (checked by the DOC-1 script list) |
| GAP-04 | No machine-readable error codes (66 domain errors, `{"detail": text}`) | M15 | **P0** | BE | none | BE-1 | Every handler response has `code`; test enumerates `DOMAIN_ERROR_RESPONSES` and asserts unique, snake_case, stable snapshot |
| GAP-05 | No rule preview endpoint (`/financial-rules/{id}/preview` absent from OpenAPI) | M03 | **P0** | BE | GAP-04 (codes for its errors) | BE-2 | Endpoint in OpenAPI; parity test (preview == executed plan on identical state); no-write test (row counts and `financial_events` unchanged); ownership test |
| GAP-06 | Expenses and Income lists unpaginated | M16 | P1 | BE | GAP-04 | BE-3 | `limit/offset/total` contract; backward-compatibility test for the shipped client; boundary tests; seeded 5k perf record |
| GAP-07 | Mobile has no CI | M19 | **P0** | MF | none | MF-1 | Workflow runs `npm ci`, `tsc --noEmit`, `npm run lint`, Node tests on PR; required status on `main` |
| GAP-08 | No request timeout, no typed API error, no 401 handling, no cache clear on sign-out | M11 | **P0** | MF | GAP-07 | MF-2 | Node tests for the pure policy helpers; staging drill: expired token → sign-out + sign-in prompt in one request; hung request ends at the timeout |
| GAP-09 | No Retry on load errors, no pull-to-refresh, no focus refetch | M12 | **P0** | MF | MF-2 | MF-3 | Every list/detail screen's error state has Retry; pull-to-refresh on every list; checklist signed per screen |
| GAP-10 | Sign-up and password recovery missing | M14a/b | **P0** | MF | QA-1 (Supabase staging), B9 | MF-4 | Staging drill on iOS and Android: register → confirm (if enabled) → sign in; request recovery → open link → set password → sign in; no account-existence leak |
| GAP-11 | URL scheme is generic (`mobile`) | B9 | **P0** | MF | none | MF-4 | `app.json` scheme app-unique; redirect URL allowlist on staging contains it |
| GAP-12 | Query keys for new families undefined; receipts key lacks user id | M21 | **P0** new / P1 receipt | MF/F | MF-2 | F-1 / MF-5 | Key registry file with tests of invalidation sets (as `goal-cache.test.mjs`) |
| GAP-13 | Rules feature absent from mobile (types, services, keys) | M01 | **P0** | F | GAP-04, GAP-08 | F-1 | Typed discriminated unions match OpenAPI; services cover all 9 rule operations; unit tests |
| GAP-14 | Evaluate not triggered by the app | M10 | **P0** | F | F-1 | F-1/F-4 | Evaluate called on foreground and Inbox open (debounced); test of the debounce helper; staging scenario shows exactly-once executions |
| GAP-15 | Manual floor warning not shown; `warnings[]` untyped | M08 | **P0** | F | F-1 | F-2 | Type includes `warnings`; device case: reservation below floor shows warning and still succeeds; replay case renders what the response carries |
| GAP-16 | Account floor/holds/rule-capacity not typed or shown | M09 | P1 | F | F-1 | F-2 | Fields typed; Account screens show them with the approved copy |
| GAP-17 | Rules list/editor (four types) | M01/M02 | **P0** | F | F-1, designs | F-3 | Device journeys J13, J14 (CONFIRM path) pass; copy checks C1–C3 |
| GAP-18 | Inbox, proposals, alerts | M04–M06 | **P0** | F | F-1, F-3 | F-4 | Journeys J15, J16 pass; proposal result read from `status`; `available:false` states distinct |
| GAP-19 | Preview UI and AUTO enable gating | M03 | **P0** | F | BE-2, F-3 | F-5 | AUTO enable disabled until a preview for the current rule version was shown; journey J14 passes |
| GAP-20 | Execution history UI and reason-code mapping | M07 | P1 | F | F-1 | F-6 | Every known `reason_code` has copy; unknown code uses fallback (unit test) |
| GAP-21 | No staging environment | M22 | **P0** | QA | owner inputs | QA-1 | Staging backend + DB + Supabase project documented, migrated, seeded; reset command guard test; no production credentials present |
| GAP-22 | Device matrix undefined/unrun; Android UNKNOWN | M22 | **P0** | QA | QA-1 | QA-0, QA-4 | Floors pinned (iOS 15.1 / API 24 unless Expo floor higher); checklist executed on ≥1 physical iOS and ≥1 physical Android; results stored |
| GAP-23 | Backend CI PG16 only; JWT verification path not in CI | — | P1 | QA | none | QA-2 | CI matrix includes PG17; test with locally signed token against the verification path |
| GAP-24 | No migration-with-data upgrade test | — | P1 | QA | none | QA-2 | Representative rows at each revision upgrade to head with invariants asserted |
| GAP-25 | No performance baseline; unbounded lists | M16 | P1 | QA | BE-3 | QA-3 | Seeded 5k expenses + 5k income baseline recorded; later runs compared |
| GAP-26 | Accessibility only partly labeled | M20 | P1 | MF/F | designs | MF-5 / each F task | Script counts accessible name+role on all interactive elements of P0 screens = 100%; manual screen-reader pass recorded |
| GAP-27 | Server-date label missing | M18 | P1 | MF | none | MF-5 | Labels present on transfers, goal transactions, overview, budget dates |
| GAP-28 | Unattended execution unverified (no Cron) | M17 | P1 (only if claimed) | OPS | GAP-01, GAP-02 | OPS Gates H/I | Gate I evidence, or UI strings contain no unattended claim (grep check) |
| GAP-29 | Production state UNKNOWN | B4 | **P0** for Beta | OPS | owner authorization | OPS Gate A | Gate A output stored |
| GAP-30 | E9A/E10 not verified applied in production | B1 | **P0** for Beta (alerts) | OPS | GAP-01, GAP-29 | OPS Gates B–G | Post-checks PASS (guarded runner) |
| GAP-31 | No automated OpenAPI/mobile type drift check | G04 | P1 | BE/MF | BE-1 | BE-4 | CI job compares committed OpenAPI snapshot; mobile types checked against it |
| GAP-32 | Copy rules (C1–C3) not enforced | decision | P1 | MF/F | F-1 | F-1 | Grep-based check of string literals for forbidden phrases runs in CI |

## 2. Counts (for gate BR-1)

Open P0 gaps today: GAP-01, 02, 04, 05, 07, 08, 09, 10, 11, 12, 13, 14, 15, 17, 18, 19, 21, 22, 29, 30 = **20**.
(GAP-29 and GAP-30 are P0 for Beta, not for MVP functional completeness.) Open P1: 03, 06, 16, 20, 23, 24, 25,
26, 27, 28, 31, 32 = **12**. P2 items live in the scope register (M13 and others); they have no gap rows.

## 3. Intentionally unused API endpoints (not gaps)

`POST /receipts`, `GET /receipts`, `PATCH /receipts/{id}`, `DELETE /receipts/{id}`: unused by decision (Q6 deferral).
The nine `financial-rules`, four `rule-proposals`, two `rule-alerts` and one `rule-executions` operations are
**unused because the mobile feature is missing**, which is the gap list above.
