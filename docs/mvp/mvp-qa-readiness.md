# MVP QA Readiness Audit (VF-MVP-ENG-001, Part 7)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.

Rules for this document: it does not configure production test access, does not run anything against an
unverified database, and distinguishes **existing evidence** (CI configuration and earlier recorded results) from
**checks executed during this task** (listed in the audit document, section 6). Counts are static
(`def test_` occurrences) unless a run is named.

## 1. Layer-by-layer audit

| # | Layer | Evidence found | Automated? | Gap |
|---|---|---|---|---|
| 1 | Backend unit tests | `tests/unit`: 897 test functions (accounts 180, goals 138, receipts 126, analytics 107, expenses 78, income 71, budgets 70, core 63, fx 26, auth 19, categories 15, settings 4) + `test_database_safety.py`. "Unit" means layer-focused; they use real PostgreSQL | Yes, in CI | No unit coverage listed for financial_rules schemas/services (covered at integration level) |
| 2 | Backend integration tests | `tests/integration`: 1116 functions (financial_rules 471, goals 211, analytics 87, accounts 80, financial_events 61, expenses 55, receipts 49, income 35, categories 29, budgets 28, settings 8, auth 2) | Yes, in CI | `GET /rule-proposals`, `/rule-executions` pagination behavior and the preview-less AUTO path need explicit contract tests when mobile consumes them |
| 3 | Database migration tests | 10 `*migration*` test files (schema checks for B/C/D/E2/E4/E6/E9A/E10 revisions, `schema_drift.py`); single-head check; CI runs `alembic upgrade head` on an empty PG16 | Yes | No upgrade-from-previous-revision-with-data test across the whole chain; production-state migrations are covered only by the OPS SQL checks (tested on disposable DBs) |
| 4 | Security and ownership | Ownership/cross-user terms appear in 82 test files (broad grep, indicative only); dev auth (`X-User-Id`) used in 5 files; 21 auth-focused tests | Yes | JWT verification against real Supabase is **not** exercised in CI (`AUTH_MODE: development`); only unit-level. RLS/Data API revocation is verified by OPS SQL checks, not CI |
| 5 | Concurrency and idempotency | 14 `*concurrency*` files (accounts, goals, goal lock L0, transfers idempotency, confirm proposals, rule execution, rules); alert progress consistency tests | Yes | Cross-process dispatcher + user-triggered drain race is tested at the DB level only; no multi-device mobile scenario |
| 6 | Mobile TypeScript and lint | `npx tsc --noEmit` and `npm run lint` | **Manual only** (not in CI). Executed during this task: both exit 0 | No CI job for mobile |
| 7 | Mobile unit/integration | 6 Node test files, 62 tests, Goals helpers only (`node --test`). No component, hook or integration tests; no `test` script in `package.json` | Manual only | Zero coverage for 10 of 11 feature directories; cache-invalidation helpers other than Goals untested |
| 8 | Mobile E2E | None. Deferred by CLAUDE.md until the product is functionally complete | No | See proposed plan (section 4) |
| 9 | Physical-device testing | Acceptance recorded as user-confirmed PASS for VF-020C3 cases A–M (roadmap) with no attached logs/screenshots; Financial Overview refresh acceptance recorded **pending** | Manual | No repeatable checklist artifacts; no device matrix |
| 10 | iOS and Android coverage | iOS Simulator tooling is available in the developer environment; physical-device mode is LAN. **No evidence of any Android run** | Manual | Android: UNKNOWN. No documented OS version matrix (decision Q12) |
| 11 | Accessibility | Labels on ~10 files; no audits, no automated checks | No | Entire layer |
| 12 | Offline / network recovery | None: no offline manager, no timeout, no retry UI; idempotency attempt key lost if form left | No | Entire layer |
| 13 | Test data and reset | Backend: `tests/conftest.py` **fails closed** unless the database name ends with `_test` and deletes all application data between tests; CI creates `valor_test`. Mobile: no fixtures, no seed, no staging environment referenced in `docs/*.md` | Backend yes; mobile no | No documented staging/dev backend with seeded users for device testing |
| 14 | Performance and response time | No benchmarks, no budgets, no load test. Unbounded list endpoints (Expenses, Income, Accounts ledger, Goals history, Transfers); Dashboard issues 7 parallel queries; dispatcher is explicitly bounded by env limits | No | Entire layer; list growth is the main known risk |
| 15 | Release and rollback | OPS-02 package on `main` (runbooks, read-only SQL checks, runner, local tests of the SQL). **The fail-closed guarded runner and the Gate H stage-1b fix exist only in local commit `c4fbd73` (not on `main`)** | Partial | See [mvp-ops-dependencies.md](mvp-ops-dependencies.md) |

## 2. Existing CI evidence versus this task

**Existing CI (configuration, not re-run here):** `.github/workflows/backend-ci.yml` on push/PR to `main`: Ubuntu,
PostgreSQL 16, Python 3.9, `alembic upgrade head`, `python -m pytest -x -v`, `AUTH_MODE=development`, local
receipt storage, Tesseract OCR driver. Backend only. **No mobile job, no migration-from-data job, no OpenAPI diff
job, no dependency or secret scan job, no PostgreSQL 17 matrix** (production is Supabase 17.x per OPS notes).

**Executed during this task:** see audit section 6 (targeted pytest 108 passed, tsc exit 0, lint exit 0, Node tests
62 passed, single Alembic head). Nothing from CI or earlier sessions is presented as newly run.

## 3. Prioritized QA gap matrix

Priority: P0 = blocks Beta or financial trust; P1 = needed before MVP acceptance; P2 = needed before wider release.

| ID | Gap | Why it matters | Priority | Proposed closure |
|---|---|---|---|---|
| G01 | No mobile CI (typecheck, lint, Node tests) | Regressions in client money display ship unnoticed | P0 | Add a mobile workflow: `npm ci`, `tsc --noEmit`, `npm run lint`, Node tests |
| G02 | No 401/session-expiry handling and no request timeout | A hung or unauthorized request leaves the user stuck | P0 | Implement (M11) with Node-testable pure helpers |
| G03 | No machine-readable error codes; exact-string matching | A copy edit on the backend silently breaks client handling | P0 | Backend `code` field + contract test that every mapped error has a stable code |
| G04 | No automated check that OpenAPI and mobile types agree | Client types drift (e.g. capacity fields, `warnings` already untyped) | P1 | Generate types from `openapi.json` or add a drift test comparing declared mobile types to the schema |
| G05 | Rules, proposals, alerts have **zero** mobile coverage and no client code | MVP scope item entirely untested on device | P0 | Build with pure state-mapping helpers + Node tests first |
| G06 | Unattended execution unverified (no Cron, P50) | "Automatic" claims would be false | P0 | OPS Gates D–I with evidence; until then UI copy forbids the claim |
| G07 | Backend JWT path not exercised in CI | Production auth mode differs from CI | P1 | Test with locally signed JWT against the Supabase verification code path (no real project) |
| G08 | No PostgreSQL 17 test run | Production engine major differs from CI (16) and local (18) | P1 | CI matrix 16 and 17 |
| G09 | No migration-with-data upgrade test across the chain | A production upgrade could meet data CI never saw | P1 | Seed representative rows at each revision on a disposable DB, upgrade to head, assert invariants |
| G10 | No physical-device acceptance artifacts; Android UNKNOWN | Cannot claim cross-platform | P0 | Written device checklist (section 4) executed on one iOS and one Android device; store results |
| G11 | No accessibility audit | Excludes users; store review risk | P1 | Screen-reader pass per surface using the state document |
| G12 | No offline/network recovery tests | Dropped responses are the idempotency use case | P1 | Manual matrix: airplane mode mid-submit for each idempotent action; automated for attempt-key helpers |
| G13 | No performance baseline or budget | Unbounded lists | P1 | Seed 5k expenses/income on a disposable DB, record endpoint timings and Dashboard load, and judge them against the absolute budgets of [mvp-readiness-gates.md](mvp-readiness-gates.md) §2.2 as well as the baseline |
| G14 | No staging environment documented | Device testing risks real data | P0 | Define a disposable/staging backend + DB with seeded users; forbid production for QA |
| G15 | Pagination absent for most lists | Performance and memory | P1 | Q7 decision then contract tests |
| G16 | Financial Overview refresh device acceptance pending | Recorded open item | P2 | Verify on first suitable real transaction |
| G17 | Release gate documents on `main` lack the fail-closed runner | Production migration safety | P0 | Publish `c4fbd73` through the normal PR path (needs user authorization) |
| G18 | Dispatcher/user-drain/mobile-evaluate triple-trigger interplay untested end to end | Duplicate or missed executions | P1 | Staging scenario: record income, call `evaluate`, run dispatcher locally against the disposable DB, assert exactly-once executions |

## 4. Proposed safe, repeatable testing architecture

Principles: disposable databases only; development or staging backends only; production is never a test target and
no production credential is placed in any test configuration.

```text
                    ┌────────────── developer machine / CI ──────────────┐
 Layer A  backend   │ PostgreSQL (docker) DB name must end _test         │  pytest, fail-closed name guard
          unit+int  │ matrix: PG16 (CI) + PG17 (new)                     │  (exists)
                    └─────────────────────────────────────────────────────┘
 Layer B  contract    OpenAPI generated offline (no DB) -> committed snapshot or diff check -> mobile type check
 Layer C  mobile      tsc + eslint + Node tests of pure helpers (cache sets, error mappers, state mappers)
 Layer D  staging     separate backend + separate Supabase project/DB, seeded test users, migrated by the
                      same guarded runner used for production rehearsal; reset script drops and recreates
 Layer E  device      Expo build pointed ONLY at the staging API; physical iOS + Android checklist; results stored
 Layer F  E2E         deferred until functionally complete; candidate: Maestro or Detox against staging
 Layer G  ops rehearsal  restore-and-verify of a backup into a disposable local DB (pattern already proven in the
                      OPS-02 package); run E9A/E10 runner there first
```

Rules:
1. **Reset strategy:** staging reset = recreate database from `alembic upgrade head` (the staging-only bootstrap, not the guarded
   production runner) plus a seed script that creates named test users, Accounts, Goals, Budgets and rules. Seeds contain no
   real data. Bootstrap and reset refuse any target that fails the identity guard in
   [mvp-ops03-and-staging-prerequisites.md](mvp-ops03-and-staging-prerequisites.md) §2.5 (allowlist, production denylist,
   empty-database check, explicit environment flag); a `_test`/`_staging` suffix alone is never enough. The guarded E9A/E10
   runner is rehearsed separately from the exact prerequisite revisions (QA-2).
2. **Test users:** at least two users per scenario to prove ownership isolation (cross-user 404).
3. **Time:** server "today" is the unit of truth; scenarios that depend on dates (planned transfers, expiry 168 h,
   budget periods) need a controllable clock in backend tests (already used) and a documented manual procedure on
   staging (create data with explicit dates; for proposal expiry use the backend test layer, not wall-clock waiting).
4. **Idempotency drills:** for Goal transactions and transfers: submit, drop the network after send, retry; assert one
   row. Repeat for confirm/reject (200 terminal state).
5. **Dispatcher rehearsal:** run `python -m app.modules.financial_rules.dispatcher` locally against the disposable DB
   with `RULE_DISPATCHER_ENABLED=true`; assert exactly-once executions and a clean summary. Never against production
   without Gate authorization.
6. **Device checklist (per release candidate):** one iOS and one Android device, staging API, journeys J01–J18 steps
   marked possible at that time, each with expected values recorded as a table; screenshots optional; failures filed.

## 5. Minimum QA exit for each readiness tier

| Tier | QA evidence required |
|---|---|
| UX research/wireframes | None beyond this audit |
| High-fidelity UI specs | Open decisions Q1–Q12 answered; state matrix reviewed |
| Implementation | G01, G02, G03 planned; staging environment (G14) defined |
| Beta | G01–G06, G10, G14, G17 closed with stored evidence; Gate I observed for any "automatic" claim |

---

## v1.1 Addendum (VF-MVP-ENG-003)

Gap IDs G01–G18 above are mapped to the new gap matrix ([mvp-engineering-gap-matrix.md](mvp-engineering-gap-matrix.md))
and closure tasks ([mvp-engineering-qa-roadmap.md](mvp-engineering-qa-roadmap.md)). The device matrix is decided (Q12):
floors iOS 15.1 and Android API 24 from the installed React Native 0.86.3 (Expo SDK 57 floor to be confirmed in QA-0),
plus latest stable, at least one physical iOS and one physical Android device. Measurable Beta criteria are in
[mvp-readiness-gates.md](mvp-readiness-gates.md). New test drills required by v1.1: registration and recovery on staging
(J19, J20), preview parity and no-write tests (BE-2), error-code uniqueness test (BE-1), pagination compatibility test (BE-3),
forbidden-copy check (C1–C3).
