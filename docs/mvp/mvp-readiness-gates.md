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
| DR-6 | Terminology and copy rules frozen (glossary, C1–C6, forbidden phrases) | handoff index section 4 | **PASS** after this task; owner acknowledgement recommended |
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

Beta is claimed only when **all** pass.

| Gate | Criterion (measurable) | How measured | Evidence | Today |
|---|---|---|---|---|
| BR-1 | Open P0 gaps = 0 | Count of P0 rows not closed in the gap matrix | gap matrix with closure evidence | **FAIL** (20 open) |
| BR-2 | CI green on `main`: backend on PG16 and PG17; mobile `tsc`, lint, Node tests | CI run on the release commit | run URLs/SHA | **FAIL** (no mobile CI, no PG17) |
| BR-3 | Test suite integrity: backend full suite 0 failed; mobile Node tests 0 failed; every new pure mapper/invalidation helper has tests | CI logs; file listing | CI | PARTIAL |
| BR-4 | OPS: S1 and S2 corrections merged; Gate A output stored; E9A and E10 applied and verified by the guarded runner post-checks (needed for live alerts) | Gate evidence files | operator-stored output | **FAIL** (UNKNOWN) |
| BR-5 | Device acceptance: journeys J01–J20 (those built) pass on ≥1 physical iOS and ≥1 physical Android device against staging; floor-OS runs on simulator/emulator at iOS 15.1 and API 24 (or the Expo floor if higher); zero open Sev-1/Sev-2 defects | Signed device checklist table | stored results | **FAIL** (none) |
| BR-6 | Idempotency drills: for Goal transaction create and transfer create, a dropped response + retry yields exactly one row; proposal confirm replay returns the terminal state with no second effect | Staging drill log + DB row counts | stored | **FAIL** |
| BR-7 | Session and timeout: an expired/invalid token yields sign-out with a sign-in prompt within one request; a hung request ends at the configured timeout (*initial*: 30 s, uploads 60 s) with a Retry state; no screen waits indefinitely | Staging drills + Node tests of the policy helpers | stored | **FAIL** |
| BR-8 | Accessibility: accessible name and role on 100% of interactive elements of P0 screens (script count); manual screen-reader pass of J01–J12 and J15–J16 on both platforms with zero critical findings | Script output + pass notes | stored | **FAIL** |
| BR-9 | Performance (*initial*): with 5k expenses and 5k income seeded on staging, Expenses/Income list first page p95 ≤ 2× the QA-3 baseline for page size, and Dashboard cold load ≤ 3 s on the reference device | QA-3 baseline + runs | stored | **FAIL** (no baseline) |
| BR-10 | Security: cross-user ownership test (second user gets 404) for every new endpoint (preview, paginated lists); no secrets in the client bundle (scan); registration/recovery review (no account-existence leak, redirect allowlist, scheme unique, no token logging) | Tests + review report | stored | **FAIL** |
| BR-11 | Documentation truth: audit D1–D12 and ops R1–R7 corrected; roadmap states only verifiable facts | DOC-1/OPS3-2 grep checks | merged PRs | **FAIL** |
| BR-12 | Rules end to end on staging: AUTO, CONFIRM confirm/reject, floor warning, overcommitment and budget alerts, proposal expiry (backend test layer), exactly-once under the three triggers (evaluate, post-Income drain, local dispatcher run) | Staging scenario script + DB assertions | stored | **FAIL** |
| BR-13 | Copy truth: forbidden-phrase check passes (no unattended claim, no "transfer" for reservation, no aggregate balance wording); AND either Gate I evidence exists or no UI string claims unattended execution | grep check + Gate I | CI/grep + evidence | PARTIAL |
| BR-14 | Rollback rehearsal on a disposable database (restore + downgrade of E9A/E10 or equivalent) completed | Rehearsal log | stored | **FAIL** |

## 3. Tier summary (A–E)

| Tier | Status | Blocked by |
|---|---|---|
| A. UX research and wireframes | **READY** | nothing |
| B. High-fidelity designs | **READY for foundation and auth surfaces after DR-1 merge and DR-9; rules surfaces additionally need DR-8** | DR-1, DR-8, DR-9 |
| C. Implementation | **READY** for OPS3-1, MF-1, MF-2, MF-3, BE-1, QA-0, QA-2; MF-4 needs QA-1; F tasks need the dependencies in the roadmap | listed per task |
| D. Full E2E testing | **NOT READY** | QA-1 staging, product built (F-6), QA-5 tool selection (deferred per CLAUDE.md) |
| E. Beta | **NOT READY** | BR-1..BR-14 |
