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
| Explicit reset | `staging_ops/reset.py`, `staging_ops/database.py` |
| Deterministic seed | `staging_ops/seed_scenarios.py`, `staging_ops/seed.py` |
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
| 8 | Not a transaction-mode pooler (port 6543 / pgbouncer); TLS required for any non-loopback host | `POOLER_UNSUPPORTED`, `TLS_REQUIRED` |
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
| R6 | Read-only OPS SQL checks on staging, for example `docs/operations/sql/run_readonly_check.sh e10_postcheck <database>` with `REQUIRE_DATA_API_ROLES=no` only for a database without the Supabase roles | Operator | `NOT RUN` |
| R7 | Create the two Auth users in the staging project ([checklist](supabase-auth-checklist.md)); write the users file (`{"QA-A": "<auth user id>", "QA-B": "<auth user id>"}`) outside the repository | Owner | `BLOCKED` |
| R8 | `seed` | Operator | `NOT RUN` |
| R9 | Mobile build fingerprint check with the QA-0 helper ([configuration](backend-and-mobile-configuration.md)); record the staging entry in the QA-0 register | Builder + owner | `NOT RUN` |
| R10 | One end-to-end sign-in from a device build against staging only (QA-1 exit criterion; recorded as QA-4 evidence) | Tester | `NOT RUN` |
| R11 | Store the sanitized evidence records (section 9) | Operator | `NOT RUN` |

## 7. Reset and recovery

Reset is a separate, explicitly destructive operation. It is **never** run after an ordinary test failure; nothing in CI, a test or a
script calls it (a repository test asserts this).

1. Full identity guard, then the Supabase probe and the connected-identity check.
2. The tool prints exactly what will be destroyed: every table with its exact row count, and the number of other objects in
   `public` (views, sequences, types, functions). It states that **Supabase Auth users, Storage objects and other schemas are not affected**.
3. The operator types the exact target identity, `<STG id>/<database>@<host>:<port>`, at an **interactive terminal**. Piped
   input is refused, so `yes | ...` cannot confirm. A different database name or host is refused.
4. The identity is re-probed after the human step.
5. All application objects in `public` that no extension owns are dropped in **one transaction** under an advisory lock; the
   transaction commits only if nothing unexpected remains. Supabase-managed schemas and roles are never touched.
6. The database is checked empty, rebuilt to the single head by the same controlled bootstrap, and verified.
7. Evidence is written. The seed must be run again.

Recovery: after `UPGRADE_FAILED` or a failed reset the database may be partly built. Do not retry the bootstrap; run the reset. A
half-seeded actor is refused by the seed (`ACTOR_HAS_DATA`) and also needs the reset. Staging data is synthetic and disposable, so no
backup is taken; production backups are out of scope.

## 8. Seed scenarios

The seed runs the backend domain services (not direct ledger writes) for two synthetic actors. All dates derive from one `as_of`
date, all income and expenses are in the base currency EUR (a USD account is funded by its opening balance), so **no exchange-rate
lookup and no network access** is needed. An actor is complete when the account `QA-SEED-<staging id>` exists (created last). Running
the seed again changes nothing.

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
