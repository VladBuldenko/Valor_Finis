# MVP Readiness Gates: Design-Ready and Beta-Ready (VF-MVP-ENG-003)

Date: 2026-10-27. Supersedes the tier assessment in [mvp-design-readiness.md](mvp-design-readiness.md) (kept as history).
A gate passes only when its **evidence** exists and is stored (a committed file, a CI run URL/SHA, or a signed
checklist). "Today" is the status on `main` @ `08d985c` plus documentation commit `7754a94` and this task.
Numeric thresholds marked *initial* are engineering proposals the owner may adjust; changing one requires a
recorded edit to this file.

## 1. Design-Ready gates (DR)

| Gate | Criterion (measurable) | Evidence | Today |
|---|---|---|---|
| DR-1 | Scope v1.1 committed; merged to `main` by the user | `mvp-scope-v1.1.md` on `main` | PARTIAL: committed locally; merge pending (user action) |
| DR-2 | Decisions recorded: 12 of 12 with option and effect | `mvp-decision-record.md` has 12 rows, none "pending" | **PASS** |
| DR-3 | Screen coverage: every route screen file under `apps/mobile/app` (28 today) appears in the inventory; every planned surface has an ID | Script: set(routes) ⊆ inventory; planned surfaces R-01..R-12 and A-01..A-03 listed | **PASS** after this task (inventory addendum) |
| DR-4 | State coverage: every P0 surface has an explicit state table (states applicable or `n/a`) | `screen-state-and-design-requirements.md` section per surface incl. addendum for auth, pagination, preview | **PASS** after this task |
| DR-5 | Contract coverage: every MVP action maps to an OpenAPI operation, a Supabase Auth client call, or a labelled planned contract (BE-1/2/3) | contract matrix addendum; count of unlabelled "no endpoint" = 0 | **PASS** after this task |
| DR-6 | Terminology and copy rules frozen (glossary, C1–C8, forbidden phrases) | handoff index section 4 | **PASS** after this task; owner acknowledgement recommended |
| DR-7 | Journeys J01–J20 each have entry, actions, calls, errors and acceptance criteria | `mvp-user-journeys.md` + addendum | **PASS** after this task |
| DR-8 | Requirement sheets for BE-1, BE-2, BE-3 accepted (design depends on error copy, preview states, list paging) | roadmap section 3 + owner acknowledgement | PARTIAL: written; owner acknowledgement pending |
| DR-9 | Wireframes of all P0 surfaces reviewed by the owner | design-side artifact | NOT STARTED (design work) |
| DR-10 | Open product decisions = 0 | decision record | **PASS** |

**DR-A (ready for UX research and wireframes):** DR-2, DR-3..DR-7, DR-10 — **MET**. Wireframing may start now.
**DR-HF (ready for high-fidelity specs of a surface family):** DR-1, DR-8 and DR-9 for that family. Foundation
surfaces (J01–J12, plus registration and recovery) need DR-1 and DR-9 only; rules surfaces also need DR-8.
**DR-I (ready for implementation of a task):** the task's dependencies merged, its high-fidelity spec approved
(for UI tasks), and for rules tasks BE-1 merged (F-5 also BE-2). MF-1, MF-2, BE-1, OPS3-1, QA-0 need no design input.

## 2. Beta-Ready gates (BR)

Beta is claimed only when **all** pass. The gates fall into two groups that are **reported separately** and both must pass:
**functional completeness** (BR-1 functional counts, BR-5, BR-6, BR-7, BR-8, BR-12, BR-13) and **production readiness** (BR-1
production-readiness counts, BR-2, BR-3, BR-4, BR-9, BR-10, BR-11, BR-14). Passing one group says nothing about the other.

| Gate | Criterion (measurable) | How measured | Evidence | Today |
|---|---|---|---|---|
| BR-1 | **Gap closure, counted separately for functional completeness and production readiness** (inventory in §2.1): every in-scope **P0 and P1** item is Closed with stored evidence. P0 may not be waived. A P1 may be left open only with an owner-signed waiver recorded in the decision record (reason, date, journeys affected). Reported as four numbers: functional P0, functional P1, production-readiness P0, production-readiness P1 | §2.1 table reconciled with the gap matrix: every `M` item in scope v1.1 and every `GAP` row appears exactly once and has a closing task and evidence | gap matrix with closure evidence + waiver records | **FAIL** (functional P0 13 open, functional P1 6, production P0 7, production P1 6; none closed) |
| BR-2 | CI green on `main`: backend on PG16 and PG17; mobile `tsc`, lint, Node tests | CI run on the release commit | run URLs/SHA | **FAIL** (no mobile CI, no PG17) |
| BR-3 | Test suite integrity: backend full suite 0 failed; mobile Node tests 0 failed; every new pure mapper/invalidation helper has tests | CI logs; file listing | CI | PARTIAL |
| BR-4 | OPS: S1 and S2 corrections merged; Gate A output stored; E9A and E10 applied and verified by the guarded runner post-checks (needed for live alerts) | Gate evidence files | operator-stored output | **FAIL** (UNKNOWN) |
| BR-5 | Device acceptance: **all of J01–J20**, each exercised end to end, pass on ≥1 physical iOS and ≥1 physical Android device against staging (not "those built": a journey whose feature is not built is a failure of BR-1, not an exemption); only J18 (execution history, P1) may be marked n/a, and only under the owner-signed P1 waiver of GAP-20, and a P1 waiver removes only the waived element from a journey's checklist. Floor-OS runs on simulator/emulator at iOS 15.1 and API 24 (or the Expo floor if higher); zero open Sev-1/Sev-2 defects | Signed device checklist with one row per journey per platform (J01–J20 × 2 = 40 rows, each PASS or waived with reference) | stored results | **FAIL** (none) |
| BR-6 | Idempotency drills: for Goal transaction create and transfer create, a dropped response + retry yields exactly one row; proposal confirm replay returns the terminal state with no second effect | Staging drill log + DB row counts | stored | **FAIL** |
| BR-7 | Session and timeout: an expired/invalid token yields sign-out with a sign-in prompt within one request; a hung request ends at the configured timeout (*initial*: 30 s, uploads 60 s) with a Retry state; no screen waits indefinitely | Staging drills + Node tests of the policy helpers | stored | **FAIL** |
| BR-8 | Accessibility: accessible name and role on 100% of interactive elements of P0 screens (script count); manual screen-reader pass of J01–J12 and J15–J16 on both platforms with zero critical findings | Script output + pass notes | stored | **FAIL** |
| BR-9 | Performance, **absolute and relative**: with the §2.2 seed on staging, **every** absolute budget of §2.2 is met under both network profiles **and** the regression thresholds hold (list first page p95 ≤ 2× the stored QA-3 baseline and ≤ +25% against the previous accepted run). Relative thresholds never excuse a missed absolute budget, and a baseline that itself exceeds an absolute budget is a FAIL. Numeric targets, the reference devices and the network profiles must first be **accepted by the owner** (decision record, acceptance parameters) | QA-3 runs per §2.2 on the reference devices; results table with raw samples | stored | **FAIL** (no baseline; owner acceptance pending) |
| BR-10 | Security: cross-user ownership test (second user gets 404) for every new endpoint (preview, paginated lists); no secrets in the client bundle (scan); registration/recovery review (no account-existence leak, redirect allowlist, scheme unique, no token logging) | Tests + review report | stored | **FAIL** |
| BR-11 | Documentation truth: audit D1–D12 and ops R1–R7 corrected; roadmap states only verifiable facts | DOC-1/OPS3-2 grep checks | merged PRs | **FAIL** |
| BR-12 | Rules end to end on staging: AUTO, CONFIRM confirm/reject, floor warning, overcommitment and budget alerts, proposal expiry (backend test layer), exactly-once under the three triggers (evaluate, post-Income drain, local dispatcher run) | Staging scenario script + DB assertions | stored | **FAIL** |
| BR-13 | Copy truth: forbidden-phrase check passes (no unattended claim, no "transfer" for reservation, no aggregate balance wording); AND either Gate I evidence exists or no UI string claims unattended execution | grep check + Gate I | CI/grep + evidence | PARTIAL |
| BR-14 | Rollback rehearsal on a disposable database (restore + downgrade of E9A/E10 or equivalent) completed, **and** the guarded-runner rehearsal E6 → E9A → E10 from exact prerequisite revisions with data on PG16 and PG17, including refuse-without-invoking negative cases ([ops03 §2.5](mvp-ops03-and-staging-prerequisites.md)) | Rehearsal logs | stored | **FAIL** |

### 2.1 Completeness inventory (feeds BR-1 and BR-5)

Class **F** = functional completeness, **P** = production readiness. `M` items are from [mvp-scope-v1.1.md](mvp-scope-v1.1.md);
`GAP` rows from [mvp-engineering-gap-matrix.md](mvp-engineering-gap-matrix.md). M13 (receipts list) is P2/deferred and
excluded. Reconciliation rule: every `M` item above P2 and every `GAP` row appears here exactly once; a row missing from
this table or from the gap matrix fails BR-1.

| Item | Priority | Class | Gap rows |
|---|---|---|---|
| M01, M02 rules and modes | P0 | F | GAP-13, GAP-17 |
| M03 preview and AUTO gating | P0 | F | GAP-05, GAP-19 |
| M04, M05, M06 proposals, alerts, Inbox | P0 | F | GAP-18 (M05 live behavior also GAP-30) |
| M08 manual-reservation floor warning | P0 | F | GAP-15 |
| M10 evaluate triggers | P0 | F | GAP-14 |
| M11 session expiry, timeout | P0 | F | GAP-08 |
| M12 retry (P0), offline cues (P1) | P0/P1 | F | GAP-09 |
| M14a/b registration, recovery (+ B9 scheme) | P0 | F | GAP-10, GAP-11 |
| M15 error codes | P0 | F | GAP-04 |
| M16 rule lists paginated (P0), Expenses/Income (P1) | P0/P1 | F | GAP-06 (rule lists via GAP-13, GAP-18) |
| M21 query keys (P0 new, P1 receipt) | P0/P1 | F | GAP-12 |
| M07 execution history | P1 | F | GAP-20 |
| M09 account floor, holds, capacity | P1 | F | GAP-16 |
| M18 server-date labels | P1 | F | GAP-27 |
| M20 accessibility baseline | P1 | F | GAP-26 |
| Copy rules enforcement | P1 | F | GAP-32 |
| S1, S2 release corrections; production state and E9A/E10 applied | P0 | P | GAP-01, GAP-02, GAP-29, GAP-30 |
| M19 mobile CI | P0 | P | GAP-07 |
| M22 staging, device matrix | P0 | P | GAP-21, GAP-22 |
| M17 unattended execution (P1, only if claimed) | P1 | P | GAP-28 |
| Backend CI depth, performance baseline, other hygiene | P1 | P | GAP-03, GAP-23, GAP-24, GAP-25, GAP-31 |

Counts today: functional P0 = 13 (GAP-04, 05, 08, 09, 10, 11, 12, 13, 14, 15, 17, 18, 19), functional P1 = 6 (GAP-06, 16, 20, 26,
27, 32); production-readiness P0 = 7 (GAP-01, 02, 07, 21, 22, 29, 30), production-readiness P1 = 6 (GAP-03, 23, 24, 25, 28,
31). Total 32, all open.

### 2.2 Performance budgets and conditions (BR-9; *initial*, owner acceptance required)

Seed (QA-3, staging, release or production-like build, not a debugger-attached build): 5,000 expenses, 5,000 income,
at least 3 Accounts, 20 Categories, 10 Budgets, 5 Goals, 5 rules and 50 proposals/alerts.

| Condition | Definition |
|---|---|
| Reference device | Per platform, the lowest-specification physical device of the owner-approved Q12 matrix; model and OS recorded in the results |
| Profile W (Wi-Fi) | Device on Wi-Fi ≥ 20 Mbps, round trip to staging ≤ 50 ms |
| Profile C (constrained) | Network throttled to 9 Mbps down / 3 Mbps up, 100 ms round trip |
| Cold Dashboard load | App process killed, valid stored session, empty query cache; measured until every Dashboard section has settled (data or error) |
| Samples | ≥ 20 runs per platform and profile for screens; ≥ 200 requests for API timings; p95 from raw samples |

| Measure | Absolute budget, W | Absolute budget, C |
|---|---|---|
| Expenses and Income first page, API end to end (default page size from BE-3, ≤ 50) | p95 ≤ 800 ms, p99 ≤ 1.5 s | not measured at API |
| Expenses and Income list screen, first page rendered, warm session | p95 ≤ 2 s | p95 ≤ 4 s |
| Dashboard cold load | p95 ≤ 3 s | p95 ≤ 6 s |
| Inbox open (evaluate + three sources settled) | p95 ≤ 3 s | p95 ≤ 6 s |
| Rule preview response, API end to end | p95 ≤ 1.5 s | not measured at API |

Regression thresholds (additional, never a substitute): list first page p95 ≤ 2× the stored QA-3 baseline and ≤ +25%
against the previous accepted run for the same profile.

## 3. Tier summary (A–E)

| Tier | Status | Blocked by |
|---|---|---|
| A. UX research and wireframes | **READY** | nothing |
| B. High-fidelity designs | **READY for foundation and auth surfaces after DR-1 merge and DR-9; rules surfaces additionally need DR-8** | DR-1, DR-8, DR-9 |
| C. Implementation | **READY** for OPS3-1, MF-1, MF-2, MF-3, BE-1, QA-0, QA-2; MF-4 needs QA-1; F tasks need the dependencies in the roadmap | listed per task |
| D. Full E2E testing | **NOT READY** | QA-1 staging, product built (F-6), QA-5 tool selection (deferred per CLAUDE.md) |
| E. Beta | **NOT READY**: functional completeness group and production readiness group each NOT MET (reported separately) | BR-1..BR-14 |
