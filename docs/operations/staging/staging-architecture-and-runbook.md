# Staging Architecture and Runbook (VF-QA-1)

Date: 2026-11-03. Basis: `main` @ `c5bb80bf28a860d70bf108527624a08bbf1d32cf`.
Contracts: [OPS03 section 2](../../mvp/mvp-ops03-and-staging-prerequisites.md), [QA-0 evidence and isolation](../../mvp/qa-evidence-and-staging-isolation.md),
[readiness gates](../../mvp/mvp-readiness-gates.md). Companion documents in this folder:
[approved targets](approved-targets-spec.md), [owner inputs](owner-input-register.md), [Supabase Auth checklist](supabase-auth-checklist.md),
[backend and mobile configuration](backend-and-mobile-configuration.md), [provisioning and acceptance checklist](provisioning-and-acceptance-checklist.md).

> **Status: IMPLEMENTATION READY, STAGING NOT PROVISIONED.** This task delivered code, tests and documents only. No Supabase project,
> database, backend instance, storage bucket or build was created or contacted. Every operational row below is `NOT RUN` or
> `BLOCKED` until the owner provides the inputs in the [owner input register](owner-input-register.md) and an operator executes the
> [checklist](provisioning-and-acceptance-checklist.md). Two gates are different and must not be confused:
>
> - **Implementation readiness**: the scripts and tests exist and pass (reviewable now).
> - **Operational staging readiness**: a separate environment is provisioned, migrated, seeded and independently verified (not reached).

## 1. Purpose

Staging exists to run device acceptance (BR-5), session and timeout drills (BR-7), registration and recovery drills (MF-4, J19/J20),
rules end to end (BR-12) and performance baselines (QA-3) **without touching production**. It is a separate environment end to end.
QA-1 provides the safe means to build, reset and seed it. It does not build it.

## 2. Environment separation

| # | Component | Staging requirement | Never shared with production |
|---|---|---|---|
| 1 | Supabase project and Auth users | Own project: own URL, publishable key, secret key, Auth users, Auth settings | URL, keys, users, JWT secret, SMTP credentials |
| 2 | PostgreSQL | Own database, PostgreSQL 17 preferred, name ends `_staging`, primary (not a replica), direct or session-mode endpoint | Host, database, role passwords |
| 3 | Backend instance | Own deployment or a local container pointed only at the staging database; `AUTH_MODE=supabase` | Service, environment variables, secret store |
| 4 | Receipt storage | Own bucket in the staging Supabase project (or local driver for a local container) | Bucket, service key |
| 5 | Environment variables and secret store | A separate store with its own access list; documents list names only | Every value |
| 6 | Mobile QA build | `EXPO_PUBLIC_*` values point only at staging, verified with the QA-0 fingerprint helper | Build channel, credentials |
| 7 | Seed accounts | Two synthetic users (QA-A, QA-B) on team-controlled addresses; synthetic data only | Any customer or production data |
| 8 | Reset and recovery | Explicit reset command with typed confirmation (section 7); staging data is disposable | Backups, restore points |
| 9 | Access and operator authorization | Named operators; written owner authorization for each mutating run | Production operators' credentials |

```text
                +---------------------------+            +---------------------------+
   PRODUCTION   | Supabase project (prod)   |            | PostgreSQL (prod)         |
   (never       | Render API (prod)         |            | Storage (prod)            |
   touched)     +---------------------------+            +---------------------------+
   ------------------------------------------------------------------------------------
                +---------------------------+            +---------------------------+
   STAGING      | Supabase project (stg)    |<-- Auth -->| API instance (stg)        |
                | Auth users QA-A, QA-B     |            |   AUTH_MODE=supabase      |
                | Storage bucket (stg)      |            +-------------+-------------+
                +---------------------------+                          |
                                                          +------------v-------------+
   operator shell ---- staging_ops (identity guard) ----> | PostgreSQL (stg) `*_staging`
   (separate secret store, no production credential)      +--------------------------+
   mobile QA build ---- EXPO_PUBLIC_* ----> staging API + staging Supabase only
```

## 3. What QA-1 delivers

| Deliverable | Where |
|---|---|
| Identity guard | `services/api/staging_ops/identity.py`, `target_config.py` |
| Empty-database bootstrap | `staging_ops/bootstrap.py` (+ `alembic/env.py` binding hook) |
| Explicit reset, confined to schema `public` | `staging_ops/reset.py`, `staging_ops/reset_scope.py`, `staging_ops/database.py` |
| Deterministic, serialized seed | `staging_ops/seed_scenarios.py`, `staging_ops/seed.py` |
| Operator checks (application database, Supabase project exposure) | `docs/operations/staging/sql/` |
| Evidence and redaction | `staging_ops/evidence.py`, `staging_ops/redaction.py` |
| Tests | `services/api/tests/unit/staging_tooling/`, `services/api/tests/integration/staging_tooling/` |
| Documents | this folder |

Not delivered (blocked on the owner): the environment itself, real approved-target values, Auth users, the live runs.

## 4. The identity guard

Every mutating command (`bootstrap`, `reset`, `seed`) runs the same chain and stops at the first failure, **before** any mutation.
Refusals carry a stable code and a fixed message; they never print a URL, host, user, password or key.

| # | Check | Code on refusal |
|---|---|---|
| 1 | `--environment staging` given, and exactly that value | `ENV_FLAG_MISSING`, `ENV_FLAG_WRONG` |
| 2 | `--staging <id>` names an entry of the approved targets | `STAGING_ID_UNKNOWN` |
| 3 | No libpq override variable (`PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`, `PGOPTIONS`, `PGSSLMODE`, ...) | `CONFIG_OVERRIDE` |
| 4 | `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` set; `AUTH_MODE=supabase` | `CONFIG_MISSING`, `AUTH_MODE_CONTRADICTORY` |
| 5 | Production denylist present: at least one database host and one Supabase project | `DENYLIST_EMPTY` |
| 6 | URL is a single-host PostgreSQL URL with no identity-overriding parameter | `CONFIG_MALFORMED` |
| 7 | Target matches nothing on the denylist (host or subdomain, database name, Supabase project from the URL, the database host or the pooler user) | `DENYLIST_HIT` |
| 8 | Not a transaction-mode pooler (port 6543 / pgbouncer); TLS (`require`, `verify-ca` or `verify-full`) required for any non-loopback host; `require` does not authenticate the server, see F5 in section 12 | `POOLER_UNSUPPORTED`, `TLS_REQUIRED` |
| 9 | Host and port equal the approved entry exactly; database name equals it exactly | `TARGET_NOT_ALLOWLISTED`, `DATABASE_NOT_ALLOWLISTED` |
| 10 | Database name ends `_staging` (necessary, never sufficient) | `DATABASE_SUFFIX` |
| 11 | `SUPABASE_URL` is `https://<project-ref>.supabase.co` for the approved project; a Supabase database host or pooler user names the same project | `SUPABASE_URL_INVALID`, `SUPABASE_PROJECT_MISMATCH` |
| 12 | Live probe: the staging project accepts the configured publishable key (no redirect followed) | `SUPABASE_PROBE_FAILED` |
| 13 | The approved entry pins the database **oid** | `OID_NOT_PINNED` |
| 14 | The server that answers reports the approved database name and pinned oid, and is a primary | `CONNECTED_DATABASE_MISMATCH`, `CONNECTED_OID_MISMATCH`, `NOT_PRIMARY` |
| 15 | Identity re-probed immediately before the mutation: name, oid, server start unchanged | `IDENTITY_CHANGED` |

### 4.1 Binding the mutation to the checked identity (time of check versus time of use)

A check on one connection says nothing about another. Three bindings close the gap:

1. **Alembic child process.** Alembic opens its own connection from `DATABASE_URL`. The parent passes the verified identity
   in `VF_STAGING_BINDING`, and `alembic/env.py` re-verifies it **inside the migration transaction before any DDL**: database
   name, oid, server start, primary, advisory lock, and (bootstrap) still empty. A connection redirected by DNS, a proxy or a
   changed URL fails with `VF_STAGING_BINDING_MISMATCH` and writes nothing (tested against a real database).
2. **In-process work (reset, seed).** The engine re-verifies the identity on **every new physical connection** and closes
   it before a statement runs if it differs (`CONNECTION_IDENTITY_CHANGED`).
3. **Child environment.** The Alembic child receives a whitelist (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, the four
   configuration variables, `PYTHON_DOTENV_DISABLED=1`, the binding). No `PG*` variable and no stray `.env` can redirect it.

The hook is inert unless `VF_STAGING_BINDING` is set, so the production guarded runner and every other Alembic command are unchanged.

### 4.2 What the guard cannot prove (residual risk)

- It is only as good as the owner's approved targets and denylist. A production endpoint missing from the denylist **and**
  absent from the allowlist is still refused (it matches no staging entry); a production endpoint **entered as staging** by mistake
  is not detectable by software. The owner reviews the file.
- A byte-identical clone of the approved database that appears under the approved host, with the same oid, cannot be told
  apart. The server start time narrows this to the duration of one run.
- It does not prove Supabase Storage or Auth contents; separation of those rests on the separate staging project.
- It is a guard against mistakes, not against a malicious operator who can edit the approved file or the source.

## 5. Command reference

Run from `services/api` in a shell whose environment holds **only staging** values. Credentials come from the environment, never
from arguments.

```bash
.venv/bin/python -m staging_ops identify  --environment staging --staging STG-1 --approved-targets <FILE>
.venv/bin/python -m staging_ops bootstrap --environment staging --staging STG-1 --approved-targets <FILE> --evidence-dir <DIR>
.venv/bin/python -m staging_ops reset     --environment staging --staging STG-1 --approved-targets <FILE> --evidence-dir <DIR>
.venv/bin/python -m staging_ops seed      --environment staging --staging STG-1 --approved-targets <FILE> --evidence-dir <DIR> --users-file <FILE>
```

There is no `--force`, `--yes`, `--skip` or `--no-verify` flag. Exit status: `0` done; `11` refused before any change;
`12` failed after a change began (see the evidence record; run the reset procedure); `64` usage error.

## 6. Runbook (operational, not executed by QA-1)

| Step | Action | Who | Result |
|---|---|---|---|
| R1 | Provision the staging Supabase project and PostgreSQL ([inputs](owner-input-register.md)) | Owner | `BLOCKED` |
| R2 | Record the production denylist and the staging identifiers in the approved-targets file ([spec](approved-targets-spec.md)); store it **outside the repository**, mode 600 | Owner | `BLOCKED` |
| R3 | `identify` (read-only): confirm the target is empty and unmigrated, and read the database oid | Operator | `NOT RUN` |
| R4 | Owner copies the oid into the approved entry (`database.oid`) | Owner | `NOT RUN` |
| R5 | `bootstrap`: builds the empty database to the single head; `alembic current` equals `alembic heads` | Operator | `NOT RUN` |
| R6a | Application database security checks, [section 6.1](#61-operator-checks-application-database-a-versus-supabase-data-api-b): `run_staging_check.sh app_database_security` | Operator | `NOT RUN` |
| R6b | Supabase project exposure checks (architecture A): `run_staging_check.sh supabase_project_exposure` and the Data API observation B2 | Operator | `NOT RUN` |
| R6c | Data API parity with production hardening | Owner decision | `NOT VERIFIED` (architecture A: cannot be established on staging, see section 6.1) |
| R7 | Create the two Auth users in the staging project ([checklist](supabase-auth-checklist.md)); write the users file (`{"QA-A": "<auth user id>", "QA-B": "<auth user id>"}`) outside the repository | Owner | `BLOCKED` |
| R8 | `seed` | Operator | `NOT RUN` |
| R9 | Mobile build fingerprint check with the QA-0 helper ([configuration](backend-and-mobile-configuration.md)); record the staging entry in the QA-0 register | Builder + owner | `NOT RUN` |
| R10 | One end-to-end sign-in from a device build against staging only (QA-1 exit criterion; recorded as QA-4 evidence) | Tester | `NOT RUN` |
| R11 | Store the sanitized evidence records (section 9) | Operator | `NOT RUN` |

### 6.1 Operator checks: application database (A) versus Supabase Data API (B)

These are two different questions. A result for one is never evidence for the other.

| ID | Question | Applies to | Procedure | Status |
|---|---|---|---|---|
| A1 | Is the dedicated PostgreSQL that FastAPI uses configured safely: right database, primary, single expected Alembic revision, API role not a superuser and not able to bypass RLS or create roles, API role can use every application table, no `PUBLIC` privilege on application tables or sequences, `PUBLIC` cannot create in `public`? | The application database, every architecture | `run_staging_check.sh app_database_security` | `NOT RUN` |
| B1 | Does the staging **Supabase project's** database hold any application relation or function its Data API could expose? | Architecture A | `run_staging_check.sh supabase_project_exposure` | `NOT RUN` |
| B2 | What does the staging project's Data API (PostgREST) actually list? | Architecture A | Observation below | `NOT RUN` |
| B3 | Parity with the production Data API hardening (migration `edcfdf3f7114`; the role checks of the E9A/E10 post-checks) | Needs the real `anon`, `authenticated`, `service_role` roles **and** the application tables in the same database | **Not obtainable on architecture A** | `NOT VERIFIED` |

**Why B3 is `NOT VERIFIED` and not `PASS` or `N/A`.** Under architecture A the application tables live in a PostgreSQL that is not
behind a Data API, and the staging Supabase project holds no application tables. Hardening production's Data API exposure therefore
has no object to act on in staging, so a staging check cannot show that production's hardening works. This is a statement about what
staging can prove. It says nothing against production, whose hardening has its own gates (E9A, E10) that staging does not replace.
Parity can be established only on architecture B (application tables inside a Supabase project, with the real roles), and only if the
owner approves B in writing (OI-04).

**Why the production runner is not used for A1/B1.** `docs/operations/sql/run_readonly_check.sh` is unchanged and is the only runner for
the E9A/E10 gates. Against a database without the Supabase roles it STOPs at `data_api_roles_resolved` (a gating check), and its
`REQUIRE_DATA_API_ROLES=no` switch is refused for any remote host and for any database whose name does not end `_test`. Creating empty
stand-in roles would make it print PASS while testing nothing; that is forbidden and is pinned by a test that shows the hazard. Its
checks are also bound to specific revisions (`e10_postcheck` accepts only `c4d8a2f6e193`).

Each check below is read-only (`BEGIN READ ONLY`, rolled back, bounded timeouts, catalog metadata only). Run them in a **separate shell**
that holds only the libpq `PG*` variables of the target (the `staging_ops` shell holds none, and the runner refuses `DATABASE_URL`). A remote
host needs `PGSSLMODE=verify-full` with a trust root; `require` is refused.

```bash
# A1: application database (the database named in the approved entry)
export PGHOST=<host> PGPORT=<port> PGUSER=<application role> PGDATABASE=<database>_staging
export PGSSLMODE=verify-full PGSSLROOTCERT=<trust root file>     # PGPASSWORD or PGPASSFILE from the staging secret store
export EXPECTED_ALEMBIC_REVISION="$(cd services/api && .venv/bin/alembic heads | awk '{print $1}')"
docs/operations/staging/sql/run_staging_check.sh app_database_security "$PGDATABASE"
```

```bash
# B1: the staging Supabase project's own database (never the application database)
export PGHOST=<project host> PGPORT=<port> PGUSER=<project role> PGDATABASE=postgres PGSSLMODE=verify-full PGSSLROOTCERT=<trust root file>
docs/operations/staging/sql/run_staging_check.sh supabase_project_exposure "$PGDATABASE"
```

```bash
# B2: observe what the staging Data API lists (staging_ops identify has just passed in this shell; the key never appears in ps)
printf 'header = "apikey: %s"\n' "$SUPABASE_PUBLISHABLE_KEY" \
  | curl -K - -sS --proto '=https' --max-time 10 "$SUPABASE_URL/rest/v1/" \
  | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin).get("paths", {})))'
```

Reading the results:

- `RESULT: PASS (...)` means exactly the gating rows printed above it were `OK`. Every run also prints `DATA_API_PARITY: NOT VERIFIED`;
  keep that line in the evidence.
- `RESULT: STOP` means a gating row failed; the failing rows name the cause. Nothing is fixed by weakening the check.
- B2 is an observation, not a pass/fail: record the output. Under architecture A the expected listing contains no application path.
  Whether the project's OpenAPI endpoint answers a publishable key at all is UNKNOWN until observed; a refusal is also recorded.
- Evidence contains verdict rows and counts only, never a host, user or key. Record A1/B1/B2 under
  `docs/operations/staging/evidence/<date>-operator-checks/` only after the owner confirms the output is free of identifiers.

## 7. Reset and recovery

Reset is a separate, explicitly destructive operation. It is **never** run after an ordinary test failure; nothing in CI, a test or a
script calls it (a repository test asserts this).

1. Full identity guard, then the Supabase probe and the connected-identity check.
2. **Scope preflight.** The tool lists every object outside schema `public` that depends on an application object (a view, foreign key, trigger,
   policy, column typed by a public type, inheriting or partition table, statistics object, function, ...). If there is any, it prints them
   (redacted, at most 20) and stops with `EXTERNAL_DEPENDENCIES` **before asking for any confirmation**. Nothing is changed.
   Otherwise it prints exactly what will be destroyed: every table with its exact row count and the number of other application objects,
   and states what is not touched (below).
3. The operator types the exact target identity, `<STG id>/<database>@<host>:<port>`, at an **interactive terminal**. Piped
   input is refused, so `yes | ...` cannot confirm. A different database name or host is refused.
4. The identity is re-probed after the human step.
5. The application objects are dropped in **one transaction** under the advisory lock, by `staging_ops/reset_scope.py`:
   explicit `DROP ... RESTRICT` statements only (there is no `CASCADE` anywhere in the destroy path, and a test checks the source),
   each kind in an order that lets PostgreSQL resolve dependencies; `ACCESS EXCLUSIVE` locks on the application tables first, then the scope
   check **again inside the transaction**, then the drops, then a comparison of a fingerprint of every out-of-scope catalog definition
   taken before and after. The transaction commits only if that fingerprint is identical and nothing unexpected remains in `public`.
   Otherwise it rolls back (`EXTERNAL_DEPENDENCIES`, `EXTERNAL_OBJECT_CHANGED`, `RESET_BLOCKED`, `RESET_INCOMPLETE`, `LOCK_BUSY`,
   `RESET_FAILED`) and the database is exactly as it was.
6. The database is checked empty, rebuilt to the single head by the same controlled bootstrap, and verified.
7. Evidence is written. The seed must be run again.

### 7.1 What the reset may touch (scope) and what is guaranteed

**Scope.** Objects in schema `public` that no extension owns: tables (including partitions), views, materialized views, foreign tables,
sequences, functions, procedures, aggregates, enum, domain and range types, and standalone composite types.

**Invariant.** A reset never modifies or drops an object outside that scope. Four independent layers uphold it, so one gap is not enough:

| Layer | Mechanism | Stops |
|---|---|---|
| 1. Preflight | catalog query over `pg_depend` for out-of-scope dependents of scoped objects, before any prompt | every dependency kind PostgreSQL records, and any it cannot attribute (fail closed) |
| 2. `RESTRICT` | every `DROP` is explicit `RESTRICT`; PostgreSQL itself refuses to drop an object with a dependent not named in the same statement | ordinary dependencies, even if layer 1 missed one |
| 3. Locks and in-transaction re-check | `ACCESS EXCLUSIVE` on the application tables, then the layer-1 query again | DDL that would add a dependent after the preflight must wait for the reset or fail; tested with concurrent sessions |
| 4. Fingerprint gate | digest of every out-of-scope relation, column, constraint, default, trigger, policy, rule, inheritance link, statistics object, function and type, compared before and after the drops | automatic dependencies that `RESTRICT` does not enforce (a partition of a scoped table, extended statistics), and anything else that changed |

Each layer is tested alone against a real PostgreSQL by disabling the layers before it, with an independent oracle that compares the full
definition and the rows of everything in a stand-in `ext` schema before and after. Sixteen dependency kinds are covered (view, view on a function, materialized
view, foreign key with data, trigger, policy, column typed by a public enum, default and check constraint calling a public function, function
argument and return types, operator, domain, inheritance, partition, extended statistics), as are a public partition of an out-of-scope parent,
outbound references, the real application schema, and concurrent DDL.

**Not guaranteed, by design.**

- Privileges granted on a dropped object go with it.
- A scoped table's foreign key or a scoped view that **reads** an out-of-scope table is removed together with the application object. The
  out-of-scope table, its definition and its rows are unchanged; only PostgreSQL's internal foreign-key trigger rows on it are not compared.
- Object kinds this tool does not enumerate (operators, collations, text-search objects, casts, event triggers) are not removed. If one
  depends on a scoped object, the reset refuses (`EXTERNAL_DEPENDENCIES`); a DDL event trigger that fires on `DROP` runs as it would for any drop.
- A dependency cycle across object kinds that no ordering resolves (for example a column default that needs a function whose return type is
  that table) is refused with `RESET_BLOCKED`; remove it by hand. The tool never falls back to `CASCADE`.
- Open sessions of the staging API or other tools holding locks make the reset fail closed after the lock timeout (`RESET_FAILED`); stop them first.
- The reset does not connect to Supabase Auth or Storage; it neither deletes users nor objects there.

Recovery: after `UPGRADE_FAILED` or a failed reset the database may be partly built. Do not retry the bootstrap; run the reset. A
half-seeded actor is refused by the seed (`ACTOR_HAS_DATA`, with the tables and counts found) and also needs the reset. Staging data is synthetic and disposable, so no
backup is taken; production backups are out of scope.

## 8. Seed scenarios

The seed runs the backend domain services (not direct ledger writes) for two synthetic actors. All dates derive from one `as_of`
date, all income and expenses are in the base currency EUR (a USD account is funded by its opening balance), so **no exchange-rate
lookup and no network access** is needed. An actor is complete when the account `QA-SEED-<staging id>` exists (created last). Running
the seed again changes nothing.

**Serialization.** The whole seed holds one PostgreSQL **session** advisory lock (the staging key, shared with bootstrap and reset) on a dedicated
connection, taken before the first preflight query and released after the last write. The domain services commit between steps, so a
transaction-scoped lock would not cover the run. A competing seed, reset or bootstrap is refused at once (`LOCK_BUSY`) instead of waiting. The
lock is re-checked before every step; if its connection is lost the run stops (`SEED_LOCK_LOST`) before the next step, so at most the step
already in flight completes. The lock is advisory: it does not stop the staging API or another tool that ignores it, so the QA actors must
not be used while a seed runs. A crashed seed releases the lock with its connection.

**Partial runs: fail closed.** An actor holding data but no completion marker is refused (`ACTOR_HAS_DATA`) with the tables and counts found;
nothing is topped up, so no financial record, reservation, AUTO-rule effect or ledger event can be duplicated. Owned data means accounts,
goals, budgets, income, expenses, rules and **user-created categories** (default categories alone do not count: the category service
creates them lazily for every user). The only recovery is the reset and a complete seed. A crash during the second actor leaves the first
complete (skipped on rerun) and refuses the second. Tests cover a lost lock, crashes at several points, retries and concurrent seeds.

**Owner-consistency evidence.** After seeding, the tool checks in SQL that every single-column foreign key between user-scoped tables points to a
row of the same user, and records the checked relationships, the number of composite keys that include `user_id` (enforced by PostgreSQL itself)
and what is **not covered**. This is not a proof of cross-user isolation: API-level reads and writes, row-level policies, grants and caches
are verified with the two real Auth users against the staging API (QA-A cannot read QA-B).

| ID | Scenario | Used for |
|---|---|---|
| QA1-S01 | Accounts in two currencies (three EUR accounts, one USD account) | J02, J10 |
| QA1-S02 | Category and monthly budget | J05 |
| QA1-S03 | Income and expenses linked to accounts | J03, J04, J12 |
| QA1-S04 | Goals in two currencies | J06, J09 |
| QA1-S05 | Linked goal reservation (stable idempotency key) | J07, J08 |
| QA1-S06 | AUTO allocation rule executed on income, with execution history | J13, J14, J18, BR-12 |
| QA1-S07 | CONFIRM allocation rule leaving a pending proposal | J14, J15, BR-12 |
| QA1-S08 | Floor alert on an account | J16, J17, BR-12 |
| QA1-S09 | Budget alert after the limit is exceeded | J16, BR-12 |
| QA1-S10 | QA-B owns separate data with overlapping names (category `QA Groceries`) | cross-user isolation checks in the security procedures |

A proposal created by S07 expires after 168 hours; re-run reset and seed to refresh it. The seed manifest (scenario to entity ids,
no secrets) is in the seed evidence record and is how an acceptance run finds QA-B's ids for the cross-user checks.
Journey numbers follow [mvp-user-journeys.md](../../mvp/mvp-user-journeys.md), which is authoritative. J01 (sign-in) needs the Auth
users of step R7. J11 (receipts) uses synthetic receipt images supplied at test time; the seed creates no receipt.

## 9. Evidence

Each operation writes a JSON record (`bootstrap-<time>-NN.json` and so on) into `--evidence-dir`: operation, outcome
(`OK`, `REFUSED`, `FAILED`), refusal code, staging id, database name, a fingerprint of the host, the database oid, the server major
version, the list of checks with pass or fail, and counts. It contains **no** URL, host name, user, password, key or raw tool output.
Alembic output is shown to the operator only after redaction, and only on failure.

A statement about a database ("empty", "at head", "N rows") is made only with such a record or an assertion record of QA-0 section 6.
Without one the report says "not observed". Commit sanitized records under `docs/operations/staging/evidence/<date>-<operation>/`;
do **not** place them in `docs/mvp/qa-evidence/`, whose directories are reserved for QA-0 device runs.

## 10. Relationship to other work

| Item | Relationship |
|---|---|
| QA-0 | The fingerprint helper proves a **mobile build** targets staging; it does not replace this database guard. The QA-0 register entry for staging is filled by the owner after R9. |
| QA-2 | Guarded-runner rehearsals (E9A, E10) from exact revisions with data on PG16 and PG17 are QA-2. The bootstrap here only builds an empty database to head; it has no explicit-revision mode yet. QA-2 must add one behind the same guard. |
| MF-4 | Needs the facts in the [Supabase Auth checklist](supabase-auth-checklist.md); it must not start until R1, R7 and the Auth settings are recorded. |
| BR-5, BR-7, BR-12 | Remain **FAIL (none)**. QA-1 enables the environment but supplies no device, drill or scenario result. |

## 11. Known limitations

- The Supabase live probe and the database probe have only been exercised against fakes and a local PostgreSQL 18; the real-project
  behaviour (including a database named other than `postgres` inside a Supabase project) is UNKNOWN until provisioned. See owner input OI-04.
- `alembic current` is evaluated by reading `alembic_version`, which is what the command reads.
- The seed creates no Supabase Auth users and never invents identifiers; QA-A and QA-B must exist in the staging project first.
- Integration tests skip, reported as `NOT RUN`, where no PostgreSQL server binaries exist.

## 12. Residual risks and remediation options (independent review VF-QA-1, findings F5 to F8)

| ID | Risk | Status | Remediation option |
|---|---|---|---|
| F5 | A remote connection with only `sslmode=require` encrypts but does **not** establish server-certificate identity, so an attacker who controls routing can impersonate the server. The identity guard accepts `require` for a remote host (`identity.py`). | **Open; a requirement before real hosted provisioning.** | The owner supplies a trust root (OI-26) and the operator's connection uses `verify-full`. The operator-check runner already refuses `require` for a remote host. Until then no remote connection is made. Do not weaken TLS to make a connection work; if verification fails, stop and report. A later change can make the identity guard require `verify-full` for non-loopback hosts. |
| F6 | The approved-targets file loader checks outside-repository, regular file and not group- or other-writable, but not the owner of the file, a writable parent directory, or a change between the permission check and the read. `services/api/Dockerfile` copies the whole directory, so `staging_ops` ships in the production image (it is never imported by the API and does nothing unless run). | Open, low. The file is trusted configuration of the operator's own account. | Keep the file in a directory only the operator can write. If the image should not carry the tooling, exclude `staging_ops` and `tests` through `.dockerignore`; not done because no need was demonstrated. |
| F7 | The database identity compared before and during a run is name, oid and server start time, not the cluster `system_identifier`. A byte-identical restore of the same cluster is indistinguishable. | Open, low. Already listed in section 4.2. | Pin `system_identifier` (readable from `pg_control_system()` with the right privilege) in the approved entry; needs a role with that privilege. |
| F8 | Negative controls: one mutant (M20, "accept a comma in the host list") is **equivalent**, because a comma host is rejected by the same code in three places. | Retained as evidence, **not** counted as a caught control. | See [negative-controls.md](negative-controls.md) for the classification of every control. |
