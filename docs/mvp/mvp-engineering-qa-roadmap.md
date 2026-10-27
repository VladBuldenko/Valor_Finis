# Engineering and QA Roadmap (VF-MVP-ENG-003)

Date: 2026-10-27. Scope: [mvp-scope-v1.1.md](mvp-scope-v1.1.md). Gaps: [mvp-engineering-gap-matrix.md](mvp-engineering-gap-matrix.md).
Gates: [mvp-readiness-gates.md](mvp-readiness-gates.md).

## 1. Rules of execution (from CLAUDE.md and the approved decisions)

1. **One task, one branch**, created from a freshly updated `main`. A dependent task starts only after its
   predecessor is merged. No stacking on unmerged branches. The user performs every merge.
2. **No remote action without explicit authorization** (push, PR). Each task ends local with `READY TO PUSH`.
3. **Production release corrections (workstream OPS) are never mixed with feature work.** OPS tasks touch
   `docs/operations/**` and their tests only.
4. Any task that changes the schema follows the migration rules in CLAUDE.md. None of the tasks below needs a
   migration (see section 4); if one does, it stops and asks.
5. No production, Render or Supabase production access; staging only, after QA-1.
6. This documentation branch (`docs/VF-MVP-ENG-001-design-readiness`) must be merged by the user before tasks
   that cite its documents begin from `main`.

## 2. Dependency graph

```text
[ENG-001/003 docs merged]
        |
        +----------------------- OPS track (independent) ----------------------+
        |   OPS3-1 -> OPS3-2 -> [owner authorizes] Gate A -> B..G -> H -> I     |
        |                                                                      |
        +-- MF-1 (mobile CI) -> MF-2 (api client) -> MF-3 (refresh/retry) -> MF-5 (a11y, keys, date labels)
        |                          |
        |                          +-> MF-4 (auth: sign-up/recovery)  <- needs QA-1 Supabase staging
        |
        +-- BE-1 (error codes) -> BE-2 (preview) ; BE-1 -> BE-3 (pagination) ; BE-4 (OpenAPI drift) after BE-1
        |
        +-- QA-0 (matrix) ; QA-1 (staging) -> QA-2 (PG17/JWT/migration-with-data) ; QA-3 (perf, after BE-3) ; QA-4 (device acceptance)
        |
        +-- F-1 (rules foundation) needs MF-2 + BE-1
              F-2 (floor warning + capacity) -> F-3 (rules list/editor) -> F-4 (Inbox/proposals/alerts)
              F-5 (preview + AUTO gating) needs BE-2 + F-3
              F-6 (execution history)
        |
        +-- DOC-1 (doc corrections) ; DOC-2 (final Design-Ready acceptance) ; QA-5 (E2E, deferred until F-6 done)
```

Design runs in parallel: wireframes start now; high-fidelity specs for each F task must exist before that F task
starts (gate DR-HF).

## 3. Tasks

Every task lists: branch, scope, depends on, exit evidence (the measurable proof), and what needs authorization.

### Workstream OPS: release security corrections (OPS-03)

| Task | Branch | Scope | Depends | Exit evidence |
|---|---|---|---|---|
| **OPS3-1** | `fix/VF-OPS03-release-security-corrections` | Re-apply local commit `c4fbd73` onto a new branch from `main` (cherry-pick is allowed; rebase is not): guarded fail-closed runner, rewritten E9A/E10 runbooks, Gate H stage 1 smoke test and stage 1b read-only check, negative tests. Docs and tests only | none | Full backend suite green on local PG18; negative tests prove `alembic upgrade` is never invoked on failed guards; independent security review with no HIGH/MEDIUM; `git diff --check`; READY TO PUSH. Then (authorized) push, PR, CI green, user merges |
| **OPS3-2** | `docs/VF-OPS03-release-docs-corrections` | Release-doc defects R3, R4, R7 (stale dispatcher status, `development.md` E9A plan, readiness section), reconcile R5 revision statements to "UNKNOWN until Gate A" | OPS3-1 merged | grep-verified: no remaining hand-typed upgrade; no "local branch/NOT pushed" statements for merged PRs |
| Gate A–I | execution by the owner/operator | Production verification and migrations via the guarded runner, each with its own written authorization | OPS3-1 merged | Evidence per gate as defined in `financial-rules-production-release.md`. Nothing here is authorized by this roadmap |

### Workstream MF: mobile foundation hardening

| Task | Branch | Scope | Depends | Exit evidence |
|---|---|---|---|---|
| **MF-1** | `chore/VF-MOB-CI` | GitHub Actions workflow for mobile: `npm ci`, `npx tsc --noEmit`, `npm run lint`, Node tests; add `test` script to `package.json`. No product code | none | Workflow green on a PR; required check proposed to the user. (This task must not stage the user's pre-existing local `package.json` edits unless the user says so) |
| **MF-2** | `feat/VF-MOB-API-CLIENT` | `apiRequest`: AbortController timeout (initial values: 30 s default, 60 s multipart, tunable constants), typed `ApiError` {status, detail, code?}, 401 → sign out + clear query cache + preserved intent, retry policy: GET only, no automatic mutation retry; error mapper keyed by `code` with string fallback; pure helpers with Node tests | MF-1 | Node tests pass; staging drills (after QA-1): expired token and hung request behave per gate BR-7 |
| **MF-3** | `feat/VF-MOB-REFRESH-RETRY` | Pull-to-refresh on every list, Retry in every load-error state, refetch on app foreground (AppState focus manager), consistent loading/empty/error component | MF-2 | Per-screen checklist 100%; no behavior change to mutations |
| **MF-4** | `feat/VF-MOB-AUTH-REGISTRATION` | Sign-up, email-confirmation-pending state, forgot password, recovery deep-link handling (`detectSessionInUrl` is false, so the link is handled explicitly), reset-password screen, app-unique URL scheme in `app.json`, generic non-enumerating messages (C6) | MF-2, QA-1 | Staging drills J19, J20 on iOS and Android (gate BR-5); security review (enumeration, redirect allowlist, no tokens logged) |
| **MF-5** | `feat/VF-MOB-HYGIENE` | Receipts query key includes user id; server-date labels (M18); accessibility baseline labels for existing P0 screens; key registry | MF-3 | Script count of accessible name/role on P0 screens = 100%; key-registry Node tests |

### Workstream BE: backend API contract additions

| Task | Branch | Scope and requirement sheet | Depends | Exit evidence |
|---|---|---|---|---|
| **BE-1** | `feat/VF-API-ERROR-CODES` | Additive `code` (stable snake_case) on every error body: domain errors, auth 401s, rule-field 422, FastAPI validation (`validation_error`), 404/500 generic. `detail` unchanged. Registry documented in `docs/api-contract.md`. A code is never renamed or reused | none | Contract test enumerates `DOMAIN_ERROR_RESPONSES`; unique + snapshot; existing 2535-test suite unchanged |
| **BE-2** | `feat/VF-API-RULE-PREVIEW` | `POST /api/v1/financial-rules/{rule_id}/preview` (name per the approved contract; final request/response sheet written in the task's plan and approved before coding). Requirements: **read-only** (no rows, no outbox event, no execution/proposal/hold, no alert write); owner-scoped (foreign id → 404); input = a sample income (amount, optional source) with defaults documented; output = planned items per target, partial/skip with reason codes, capacity figures (reservable, floor, holds, rule capacity), and a response-time snapshot marker; works for AUTO and CONFIRM allocation rules; clear 409/422 for non-previewable rules; reuse the execution computation (no duplicated logic). Plan mode required (financial logic) | BE-1 | Parity test (same state: preview plan == executed plan), no-write test (table row counts unchanged), concurrency test with a real execution, ownership test, full backend suite |
| **BE-3** | `feat/VF-API-LIST-PAGINATION` | Pagination for Expenses and Income. Backward compatibility with the shipped client is a task requirement (strategy chosen in the task plan: e.g. new optional parameters and an envelope only when requested). Transfers deferred (P2) | BE-1 | Compatibility test; boundary tests; ordering stability tests; seeded 5k perf record (QA-3) |
| **BE-4** | `chore/VF-API-OPENAPI-DRIFT` | Committed OpenAPI snapshot + CI diff check; mobile type conformance check | BE-1..BE-3 | CI fails on an undeclared contract change |

No BE task adds a migration. If BE-3's ordering/performance needs an index, that becomes a separate migration task
under the CLAUDE.md migration rules.

### Workstream F: VF-020F Smart Rules mobile

Each slice requires approved high-fidelity specs (gate DR-HF) and the previous slice merged. Mobile-only; no
backend or schema changes. Copy rules C1–C6 apply.

| Task | Branch | Scope | Depends | Exit evidence |
|---|---|---|---|---|
| **F-1** | `feat/VF-020F1-rules-foundation` | Types (discriminated unions from OpenAPI), services for all rule operations, query-key registry and invalidation sets, evaluate trigger helper (foreground + Inbox open, debounced), reason-code/alert-level/status mappers, forbidden-copy check | MF-2, BE-1 | Node tests for every mapper and invalidation set; typecheck/lint |
| **F-2** | `feat/VF-020F2-floor-warning-capacity` | Manual-reservation floor warning (M08), Account floor/holds/rule-capacity display (M09) | F-1 | Device case: reservation under the floor shows the warning and succeeds; capacity strings match API values |
| **F-3** | `feat/VF-020F3-rules-list-editor` | Rules list, editors for four types, enable/pause/disable/delete, CONFIRM presented first, error handling by code | F-2 | Journeys J13, J14 (CONFIRM path) on staging |
| **F-4** | `feat/VF-020F4-inbox-proposals-alerts` | Inbox composition (M06), proposal detail/confirm/reject with `status`-driven outcomes, alerts list/acknowledge, `available:false` state, Dashboard badge | F-3 | Journeys J15, J16; exactly-once scenario with the three triggers (gate BR-12) |
| **F-5** | `feat/VF-020F5-preview-auto` | Preview UI, AUTO enable gating on a preview of the current rule version, AUTO copy rule C1 | BE-2, F-3 | Journey J14 including AUTO; preview staleness handling after rule edit |
| **F-6** | `feat/VF-020F6-execution-history` | Execution history with plain-language reasons (M07), failure/blocked explanation using counters (no invented recovery) | F-4 | Journey J18; every known reason code has copy; unknown fallback tested |

### Workstream QA: infrastructure and staging

| Task | Branch | Scope | Depends | Exit evidence |
|---|---|---|---|---|
| **QA-0** | `docs/VF-QA-DEVICE-MATRIX` | Pin the device matrix (floors per Q12; confirm Expo SDK 57 documented floors), device checklist template (journeys, expected values) | none | Matrix and template committed |
| **QA-1** | `chore/VF-QA-STAGING` | Staging runbook, seed and reset scripts (name guard `_test`/`_staging`), env variable list (names only), Supabase staging settings checklist (see [mvp-ops03-and-staging-prerequisites.md](mvp-ops03-and-staging-prerequisites.md)). **Provisioning needs owner inputs** | owner | Staging migrated to head by the guarded runner; seed/reset works; no production credential present; OPS SQL checks pass on staging |
| **QA-2** | `chore/VF-QA-BACKEND-CI-DEPTH` | PG16+PG17 CI matrix, JWT verification-path test with a locally signed token, migration-with-data tests | none | CI green on both versions |
| **QA-3** | `chore/VF-QA-PERF-BASELINE` | Seed 5k expenses/income, record endpoint timings and Dashboard load | BE-3, QA-1 | Baseline stored |
| **QA-4** | `docs/VF-QA-DEVICE-ACCEPTANCE-<n>` | Execute the checklist on devices per release candidate; store results | QA-0, QA-1, tasks under test | Results table with zero open Sev-1/Sev-2 |
| **QA-5** | later | Mobile E2E tool selection and suite | F-6 merged (product functionally complete) | Deferred per CLAUDE.md |

### Workstream DOC

| Task | Branch | Scope | Exit evidence |
|---|---|---|---|
| **DOC-1** | `docs/VF-DOC-ROADMAP-CORRECTIONS` | Audit D1–D12: roadmap, product requirements, smart-goals contract statements | grep checks listed in the task; no contradictions with `git log`/`alembic heads` |
| **DOC-2** | `docs/VF-MVP-ENG-004-design-ready-acceptance` | Evaluate gates DR-1..DR-10 with evidence, refresh handoff index and matrix | Gate table all PASS |

## 4. Schema and migration note

No task in this roadmap requires a schema change. BE-2 reads existing tables; BE-3 changes query shape only;
registration uses Supabase Auth, not application tables (default categories are created lazily by the existing
service). Any discovered need for a migration stops the task and is raised separately.

## 5. Suggested order of execution

1. Merge the MVP documentation (this branch) — user action.
2. In parallel: OPS3-1, MF-1, BE-1, QA-0; design wireframes.
3. MF-2, then MF-3; BE-2 and BE-3; QA-2.
4. Owner provides staging inputs → QA-1 → MF-4.
5. F-1 → F-2 → F-3 → F-4 → F-5 → F-6 (as high-fidelity specs land).
6. MF-5, QA-3, BE-4, DOC-1, OPS3-2.
7. QA-4 device acceptance per slice and at the end; DOC-2; production gates on the OPS track; Beta gate review.
