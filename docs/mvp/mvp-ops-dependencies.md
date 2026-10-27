# Security and Operations Dependencies (VF-MVP-ENG-001, Part 8)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.

Scope guard: this record was produced **offline from the repository and local Git only**. No production, Render or
Supabase system, credential, database or backup was accessed, and no migration was run. Everything about a
production system is therefore **UNKNOWN until verified by the operator** through the release gates.

## 1. Branch and PR status (verified from local Git on 2026-10-27)

| Item | State |
|---|---|
| `main` | `08d985c030a38823fe43863c806d90bbc86e97b4` = merge of PR #97 (OPS-02 release verification package) |
| PR #94 / #95 / #96 / #97 | E10 dispatcher / fairness + progress schema / R02 progress consistency / OPS-02 package: **all merged** |
| Remote branch `origin/docs/VF-020E10-OPS02-release-verification` | still exists, at `e759ce4e4fe8a925ff7d268cec11d5d94df0acfe` (the commit PR #97 merged) |
| Local branch `docs/VF-020E10-OPS02-release-verification` | at `c4fbd73fadd9bfec24ec83071afb8de5c2d24ea4`, **one commit ahead of the remote**: "fail-closed guarded migration runner and Gate H read-only Cron runtime check" |
| Is `c4fbd73` on `main`? | **No** (`git merge-base --is-ancestor c4fbd73 main` → 1; no remote branch contains it) |
| "OPS-03 correction branch" (task brief) | No branch with that name exists. The corrections it refers to are the single local commit `c4fbd73` above. They have **not been pushed, reviewed on a PR, or run in CI** |
| Open PRs | None known to this audit (the `gh` CLI is not authenticated here; PR state beyond merged history cannot be listed offline: UNKNOWN) |
| This task's branch | `docs/VF-MVP-ENG-001-design-readiness`, created from `main`; documentation only |

## 2. Security review findings on the OPS-02 package

| ID | Severity | Finding | State on `main` | State of the correction | Release blocker? |
|---|---|---|---|---|---|
| S1 | **HIGH** | E9A/E10 migration execution was not fail-closed: the runbooks use a hand-typed `alembic upgrade <revision>` after separate manual checks, with no enforced proof that the connected endpoint equals the checked endpoint, that `alembic current` equals the parent, or that preflight PASSed in the same flow | **OPEN.** `docs/operations/e9a-production-migration.md:140` and `e10-production-migration.md:55` still contain the hand-typed upgrade; `docs/operations/sql/run_guarded_migration.sh` does not exist on `main` | A fail-closed runner and rewritten runbooks exist **only** in local `c4fbd73`. Evidence that exists: full local backend suite on that branch recorded 2535 passed / 0 failed; 133 release-verification tests incl. negative cases proving `alembic upgrade` is never invoked on a failed guard; two independent review passes with no remaining material finding. Evidence that does **not** exist: remote CI, PR review, merge, PostgreSQL 16/17 execution | **YES — remains a release blocker until `c4fbd73` (or its equivalent) is published through the normal PR path, CI is green, and the user merges it** |
| S2 | **MEDIUM** | Gate H stage 1 claimed a disabled dispatcher run "proves the image, the environment and the database connection". A disabled dispatcher returns before opening any database session, so it proves nothing about connectivity | **OPEN.** Section 11 of `financial-rules-production-release.md` on `main` still says so | Local `c4fbd73` rewrites stage 1 as a CLI/config smoke test only and adds a read-only stage 1b runtime check (revision, tables, per-privilege checks with separate `has_table_privilege` calls, sequence USAGE). Test evidence recorded locally; the Render Docker Command quoting for stage 1b is **unverified** | **YES — remains a release blocker** until published and merged; Cron activation is blocked regardless (no job exists) |

Neither finding is marked resolved by this audit. "Corrected locally and tested locally" is not "resolved".

Residual risks recorded by the corrections (still true after `c4fbd73`): constraint comparison ignores parentheses;
a role that is a member of `pg_maintain` is not detected; a weaker `sslmode` embedded in `DATABASE_URL` is not
inspected by the runner; Supabase startup-option support and Render exit-code/notification behavior are unverified;
PostgreSQL 16/17 behavior of the SQL checks was not exercised locally (a text drift could only cause a false STOP).

## 3. Release documentation defects (known, none corrected by this task)

| # | Defect | Location |
|---|---|---|
| R1 | Hand-typed `alembic upgrade` (S1) | `docs/operations/e9a-production-migration.md:140`, `e10-production-migration.md:55` |
| R2 | Gate H stage 1 overclaim (S2) | `docs/operations/financial-rules-production-release.md` §11 |
| R3 | Stale status "implemented on the local feature branch … NOT pushed" | `docs/operations/rule-dispatcher.md` (first lines) |
| R4 | Old E9A plan with a hand-typed upgrade | `docs/development.md` (~lines 415–444); also says migration `c4d8a2f6e193` is "on a local branch, not pushed or applied" (merged) |
| R5 | Three different "current production revision" values across docs | `product-requirements.md` (`861064d31463`), `roadmap.md`/contract (`e0503e9ca9d3` as operator-supplied state); real value UNKNOWN |
| R6 | Roadmap and contract describe E7–E10 as unmerged or local | see audit D1–D7 |
| R7 | `docs/operations/financial-rules-production-release.md` §14 says "`main` `f28818b`"; `main` is now `08d985c` | §14 |

## 4. Technical state

| Item | State | Evidence |
|---|---|---|
| Alembic head | `c4d8a2f6e193` (single) | `alembic heads` run 2026-10-27 on `main`; `valor_test` migrated to it |
| Chain | `e0503e9ca9d3` (E6) → `a7c3e91d5b24` (E9A, `rule_alerts`) → `c4d8a2f6e193` (E10 progress) | repository |
| Production revision | **UNKNOWN** | requires Gate A. Operator-supplied history in docs: E6 `e0503e9ca9d3` applied 2026-10-21/22; E9A and E10 documented as not applied |
| Deployed backend SHA | **UNKNOWN** | requires Render dashboard / Gate A; the ancestry rule `git merge-base --is-ancestor f28818bc7e487c943df87ce384caad0e5eadfa71 <DEPLOYED_SHA>` decides compatibility |
| Render connectivity (web → DB, Cron → DB) | **UNKNOWN** | a historical authenticated `GET /api/v1/accounts` HTTP 500 was reported in earlier work; cause and current state unverified |
| E9A (`rule_alerts`) applied in production | **UNKNOWN** (documented as not applied) | consequence: alert rules return 409 "cannot be enabled yet"; `GET /rule-alerts` returns `available:false` |
| E10 (`alert_dispatch_progress`) applied in production | **UNKNOWN** (documented as not applied) | the dispatcher persistent-progress logic requires it |
| Render Cron Job | Documented as **not created**; existence cannot be verified offline | `rule-dispatcher.md` §3 is a proposal only; `render.yaml` must not provision it |
| Cron activation | **NOT ACTIVE (as documented)**; Gates H and I not started | |
| Unattended rule execution | **UNVERIFIED** (P50 requires an observed scheduled run) | |

## 5. Gate model (from `financial-rules-production-release.md`)

A diagnostics (read-only) → B E9A backup and restore verification → C exact E9A migration → D E9A post-check and
application validation → E E10 preflight and verified backup → F exact E10 migration → G E10 post-check, role
security, runtime compatibility → H Render Cron pricing, configuration, staged activation → I observed
scheduled-run acceptance. **Each gate needs its own written authorization; none is implied by this document.**
After S1 is published, Gates C and F must use the guarded runner and not a hand-typed command.

## 6. Evidence required before Beta

| # | Evidence | Closes |
|---|---|---|
| 1 | S1 and S2 corrections published by PR, CI green, independently reviewed, merged by the user | S1, S2 |
| 2 | Gate A output: production revision, deployed SHA(s) with ancestry result, Data API probe, connectivity, root cause of the historical HTTP 500 | UNKNOWNs in section 4 |
| 3 | Gates B–D (E9A) with backup checksum, restore proof, post-check PASS, authorized application validation | E9A applied and verified |
| 4 | Gates E–G (E10) likewise | E10 applied and verified |
| 5 | Gate H: recorded cost approval, stage 1 and 1b results | Cron configured safely |
| 6 | Gate I: an observed scheduled run with dispatcher summary and zero unexpected progress failures | P50; permission to say "runs unattended" |
| 7 | Mobile rule/proposal/alert/Inbox screens implemented and accepted on physical iOS and Android devices against staging | M01–M10 |
| 8 | Mobile session-expiry handling and timeouts (M11) and mobile CI (G01) | client resilience |
| 9 | Staging environment defined and used for all device QA (G14); no QA against production | QA safety |
| 10 | Rollback plan exercised on a disposable database (restore + downgrade rehearsal) | release safety |

## 7. What does and does not depend on this

Offline UX research, wireframes, high-fidelity specification and mobile implementation **do not** depend on
production readiness. Any claim about live alerts, unattended AUTO execution, or "Beta ready" **does**.

---

## v1.1 Addendum (VF-MVP-ENG-003)

The OPS-03 procedure, gate sequencing and staging prerequisites are specified in
[mvp-ops03-and-staging-prerequisites.md](mvp-ops03-and-staging-prerequisites.md). S1 and S2 remain **open** until their
corrections are merged to `main` with evidence.
