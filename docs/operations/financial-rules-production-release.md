# Financial rules and alerts: production release matrix (E9A, E10, Render Cron)

Status: **prepared, offline. Nothing in this document has been executed against production.** Production
revision, deployed build and connectivity are UNKNOWN until Gate A has been run. Do not assume any revision is
unapplied: every gate that changes something starts with a read-only check of the actual state.

Reference commits (all on `main`):

| Commit | Meaning |
|---|---|
| `6e4ecf8` | E9B alert runtime merged |
| `90d6341` | E10 dispatcher CLI merged |
| `0604d87` | persistent progress schema and runtime merged |
| `f28818bc7e487c943df87ce384caad0e5eadfa71` | R02 progress consistency merged: **the required commit for the whole feature set** |

Companion documents: [e9a-production-migration.md](e9a-production-migration.md),
[e10-production-migration.md](e10-production-migration.md), [rule-dispatcher.md](rule-dispatcher.md) (architecture,
process contract, Render Cron proposal, monitoring SQL). Verification scripts: [sql/](sql/).

## 1. Deployed-build rule (corrected)

A commit is part of the deployed runtime **only if it is an ancestor of the deployed SHA**:

```bash
git fetch origin
git merge-base --is-ancestor f28818bc7e487c943df87ce384caad0e5eadfa71 <DEPLOYED_SHA>; echo $?
# 0 = required commit IS included    1 = NOT included    >=128 = error (e.g. the SHA is unknown locally)
```

- Equality with the latest `main` is **not** required. A release build that is a *descendant* of the required
  commit contains it and is acceptable, whatever else it contains; a build older than it, or built from a branch
  that does not contain it (a hotfix or a stale deploy), does not, even if it was deployed recently.
- Exit status 1 for the required commit means the dispatcher's progress logic, the R02 stale-write guard and
  the alert runtime may be absent; every gate that depends on that runtime (G, H, I) is blocked until a
  compatible build is deployed. Exit status >= 128 is an error, not a pass: fetch the SHA or get the exact SHA
  from the Render dashboard again.
- To state what a build lacks, run the same check for the individual commits above.
- The web service needs only E9B (`6e4ecf8`) to use `rule_alerts`; the **cron job** needs `f28818b`. Render builds
  the Cron Job image separately, so check its deployed SHA with the same rule.

## 2. Operator conventions (every gate)

1. Each gate is authorized separately, in writing, naming the gate (and, for migrations, the exact revision).
   Approval for one gate never covers another, and never covers a retry after a failure.
2. Credentials only through the libpq environment of the operator's own shell, loaded from the approved secret
   store; never in arguments, files in the repository, chat, tickets or logs. The AI assistant used for this
   repository has no standing access to production credentials and must not be given a way to read them
   without an explicit, separate authorization of the method. `PGSERVICE`, `PGSERVICEFILE` and `PGHOSTADDR`
   must not be set (libpq lets them override the validated host and TLS settings); the runner refuses them.
6. The runner refuses to weaken its privilege checks (`REQUIRE_DATA_API_ROLES=no`, a changed role list) for any
   host other than a local test database, so a production PASS has always tested the Data API roles.
3. Use the direct or session-mode database endpoint for the runner and for Alembic. A transaction pooler rejects
   startup options and is unsuitable for DDL. (Whether the Render service itself uses a pooler, and whether the
   direct host is reachable from Render, is a Gate A finding.)
4. Save each output (counts and names only; never customer rows).
5. A STOP is an outcome, not an error to work around: report it and wait.

## 3. Gate summary

| Gate | Purpose | Changes anything? | Authorization |
|---|---|---|---|
| A | read-only diagnostics: deployed SHA, connectivity, revision, schema, the historical HTTP 500 | no | A |
| B | E9A backup and restore verification | no (reads production, writes a local dump) | B |
| C | exact E9A migration `a7c3e91d5b24` | **yes, schema** | C (names the revision) |
| D | E9A post-check and application validation | no | D (may be granted together with C, but must be named) |
| E | E10 read-only preflight and verified backup | no | E |
| F | exact E10 migration `c4d8a2f6e193` | **yes, schema** | F (names the revision) |
| G | E10 post-check, role security, runtime compatibility | no | G |
| H | Render Cron pricing, configuration, staged activation | **yes, infrastructure and recurring cost** | H (cost and activation) |
| I | observed scheduled-run acceptance | no | I (read-only queries and dashboard observation) |

If Gate A shows a migration is already applied, the corresponding migration gate is skipped **and its
post-check must PASS** before moving on.

## 4. Gate A - read-only production diagnostics

**Entry:** written authorization A. A maintenance window is not needed (read-only), but avoid peak traffic.

**Steps and evidence**

1. *Deployed revision.* In the Render dashboard (read only): web service and, if it exists, the Cron Job; record
   the deployed commit SHA, the auto-deploy setting, and the **names** (never values) of the environment
   variables `DATABASE_URL`, `AUTH_MODE`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `RULE_*`. Apply the
   ancestor rule of section 1.
2. *Connectivity without exposing credentials.* The run itself is the test: `run_readonly_check.sh` connects
   with a 10 s connect timeout and on failure prints only a sanitized first error line (host, address, port,
   user and database are replaced by placeholders).
3. *Database state.* From `docs/operations/sql`:

   ```bash
   ./run_readonly_check.sh e9a_preflight  <production_database_name>
   ./run_readonly_check.sh e10_preflight  <production_database_name>
   ./run_readonly_check.sh e10_postcheck  <production_database_name>
   ./run_readonly_check.sh e9a_postcheck  <production_database_name>
   ```

   In Gate A a `STOP` is **information**: read the `alembic_revision_*`, `*_absent`, `*_exists` rows. Decode:

   | Observation | State |
   |---|---|
   | the run fails with a connection error | database inaccessible (see 4 below); nothing else is known |
   | `e9a_preflight` PASS | at `e0503e9ca9d3`, E9A **not** applied, no partial objects: Gate B is next |
   | `e9a_preflight` STOP, `alembic_revision_is_e6_parent` actual is `a7c3e91d5b24`, and `e10_preflight` PASS | E9A applied, E10 not: run `e9a_postcheck` as the Gate D check, then Gate E |
   | `e10_postcheck` PASS **and** `e9a_postcheck` PASS (it accepts the E10 revision) | E9A and E10 are both applied and their schema and privileges match the expectation; this is not a statement about runtime health. Go to Gate G's runtime checks |
   | `e10_postcheck` PASS but `e9a_postcheck` STOP | E10 exists but `rule_alerts` does not match (or is exposed): STOP |
   | partial-object rows FAIL | a partial or foreign object exists: STOP, do not migrate, investigate |
   | revision is anything else, or more than one row | unexpected state: STOP |

4. *Distinguishing the three failure classes* (also for the historical authenticated `GET /api/v1/accounts` HTTP 500):

   | Evidence | Class |
   |---|---|
   | the runner cannot connect (`OperationalError`: host resolution, network unreachable, timeout, password or SSL failure, connection limit) | **inaccessible database**. Hypotheses to check, not facts: the direct Supabase host may be IPv6-only from the Render network (use the session endpoint), a wrong credential or `sslmode`, a connection-limit exhaustion |
   | the runner connects, revision is `e0503e9ca9d3` and `rule_alerts` is absent, and the 500 log shows `UndefinedTable`/`UndefinedColumn` | **missing schema relative to the deployed code**. Note the E9B code tolerates a missing `rule_alerts`, so this class implicates other code or revision drift |
   | the runner connects, revision and schema are as expected, and the log shows a Python traceback outside the database driver, or a 500 with an explicit message about Supabase settings (`get_supabase_auth_settings` returns 500 when `SUPABASE_URL` or the publishable key is missing; an unreachable Supabase Auth returns 503; an invalid token returns 401) | **runtime or configuration failure** |

   `GET /health` returns a static document and does **not** touch the database: a healthy `/health` proves nothing
   about connectivity.

**PASS:** the state is fully decoded, connectivity works, and the cause of the 500 (if still reproducible) is
classified. **STOP:** connectivity fails or the cause is unexplained: fix that first; no later gate may start.
**Rollback:** none needed (read-only). **Exit evidence:** the saved outputs, the SHA and the deploy settings.

## 5. Gate B - E9A backup and restore verification

**Entry:** Gate A PASS with `e9a_preflight` PASS; written authorization B.
**Procedure and evidence:** [e9a-production-migration.md](e9a-production-migration.md) section 4: logical dump,
SHA-256, `pg_restore --list`, restore into a throwaway `*_test` database, `e9a_preflight` on the restored copy.
**PASS:** the checksum verifies, the restore completes, and the restored `row_count:*` rows equal production's.
**STOP:** any mismatch or error. **Recovery:** delete the local copies per the owner's retention rule; nothing in
production changed. **Notes:** provider snapshots/PITR are additional, UNKNOWN until checked, and do not replace
the verified dump.

## 6. Gate C - exact E9A migration

**Entry:** Gate B PASS; a fresh `e9a_preflight` PASS in the same window; written authorization C naming revision
`a7c3e91d5b24`; a maintenance moment with low write traffic on `financial_rules`.
**Procedure:** [e9a-production-migration.md](e9a-production-migration.md) section 5: only
`./run_guarded_migration.sh a7c3e91d5b24 <db>`, which fails closed (endpoint proof, `alembic current`, preflight)
before the exact-revision upgrade and verifies afterwards; never a hand-typed `alembic upgrade`, never `head`.
**PASS:** the runner exits 0. **STOP:** exit 11 (nothing changed), 12 (upgrade failed, nothing committed) or 13
(migrated but a post-check failed: report); re-verify with the preflight and stop. **Recovery:** the migration is one transaction; see the E9A runbook section 8 for what a
downgrade can and cannot do. **Authorization:** C.

## 7. Gate D - E9A post-check and application validation

**Entry:** Gate C completed (or Gate A showed E9A already applied).
**Evidence:** `./run_readonly_check.sh e9a_postcheck <db>` PASS with `APP_ROLE` set; `row_count:*` rows equal to the
Gate A/B preflight; authenticated reads of `/api/v1/accounts` and `/api/v1/financial-rules` (and `/api/v1/rule-alerts`
when the deployed build contains `6e4ecf8`); `GET /health`; an external Supabase Data API request for
`rule_alerts` with the public key returns no data (401/403/404).
**PASS:** every item. **STOP:** any non-PASS row, any 5xx, any data returned to the Data API. **Recovery:** E9A
runbook section 8 (leave in place and decide; guarded REVOKE for an exposure). **Authorization:** D, which the owner may
grant together with C but must name; a later re-run needs A.

## 8. Gate E - E10 read-only preflight and verified backup

**Entry:** Gate D PASS; written authorization E.
**Procedure:** [e10-production-migration.md](e10-production-migration.md) section 2: `e10_preflight` PASS and a
**fresh** restore-verified dump (not the pre-E9A one).
**PASS / STOP:** as in that section. **Recovery:** none needed (nothing changed in production).

## 9. Gate F - exact E10 migration

**Entry:** Gate E PASS; a fresh `e10_preflight` PASS immediately before; written authorization F naming revision
`c4d8a2f6e193`.
**Procedure:** [e10-production-migration.md](e10-production-migration.md) section 3
only `./run_guarded_migration.sh c4d8a2f6e193 <db>` (same guards and exit codes). No lock on an existing table is taken.
**PASS:** the runner exits 0. **STOP:** exit 11, 12 or 13; verify with the preflight and stop. **Recovery:** see the E10 runbook
section 6; a downgrade is safe only after the dispatcher is disabled or switched to
`RULE_DISPATCHER_ALERT_PROGRESS=off` and no run is active.

## 10. Gate G - E10 post-check, role security and runtime compatibility

**Entry:** Gate F completed (or Gate A showed E10 already applied); written authorization G for the follow-up reads.
**Evidence:**
1. `APP_ROLE=<role> ./run_readonly_check.sh e10_postcheck <db>` PASS (schema, sequence, ownership, application
   access, **effective** absence of Data API and `PUBLIC` access on table and sequence) **and**
   `./run_readonly_check.sh e9a_postcheck <db>` PASS (it accepts the E10 revision and re-verifies `rule_alerts`).
2. The ancestor rule for the web service **and** the cron build: `f28818b` must be an ancestor of each deployed
   SHA. If a deployed release build is not identical to `main`, the rule decides, not equality.
3. External Data API probe for `alert_dispatch_progress` returns no data.
**PASS:** all three. **STOP:** any FAIL row; a deployed SHA that does not contain `f28818b`. **Recovery:** E10
runbook section 6.

## 11. Gate H - Render Cron pricing, configuration and staged activation

**Entry:** Gate G PASS; written authorization H that states the plan and the accepted recurring cost.
**Cost evidence to record at approval time** (look it up on the provider's pricing page that day; this document
deliberately states no price): the plan chosen, the minimum monthly charge per cron job, the prorated compute rate,
the estimated run seconds per run, and runs per month (a 10-minute schedule is 144 runs/day). The Docker image is
pulled on every run (it includes Tesseract), which affects start-up time and cost; a slimmer image is an optional
later optimization.
**Configuration:** the proposal in [rule-dispatcher.md](rule-dispatcher.md) section 3 (Docker runtime, command
`python -m app.modules.financial_rules.dispatcher`, schedule `*/10 * * * *` UTC, same database URL secret as the
web service, same region). Do not commit a `render.yaml` that provisions it automatically.
**Staged activation (each stage needs the operator to confirm the previous one):**
1. **Smoke test of the CLI and configuration only.** Create the job with `RULE_DISPATCHER_ENABLED=false` and trigger
   one run. Expected: exit 0 and a `dispatcher_summary` with `outcome: disabled`. This proves only that the image
   builds, the command starts and the configuration parses. **It does not prove database connectivity**: a disabled
   dispatcher returns before it ever opens a database session, so a successful disabled run says nothing about
   PostgreSQL, the credentials, the endpoint or the schema.
1b. **Read-only connection and schema verification through the actual Cron runtime path** (required before real
   processing is enabled). Temporarily set the Cron Job's Docker Command to the single command below and trigger one
   run, then restore `python -m app.modules.financial_rules.dispatcher`. It runs inside the Cron image with the Cron
   service's own `DATABASE_URL`, through the same engine module the dispatcher uses
   (`app.db.database_session`), starts with `SET TRANSACTION READ ONLY`, writes nothing, prints no URL, and exits
   non-zero unless every expectation holds (each table privilege is tested on its own: PostgreSQL's
   `has_table_privilege` with a list returns true when the role holds ANY listed privilege):

   ```
   python -c 'import sys; from sqlalchemy import text; from app.db.database_session import engine; c = engine.connect(); c.execute(text("SET TRANSACTION READ ONLY")); r = tuple(c.execute(text("SELECT (SELECT min(version_num) FROM alembic_version), (SELECT count(*) FROM alembic_version), to_regclass($$public.rule_alerts$$) IS NOT NULL, to_regclass($$public.alert_dispatch_progress$$) IS NOT NULL, current_setting($$transaction_read_only$$), has_table_privilege(current_user, $$public.alert_dispatch_progress$$, $$SELECT$$) AND has_table_privilege(current_user, $$public.alert_dispatch_progress$$, $$INSERT$$) AND has_table_privilege(current_user, $$public.alert_dispatch_progress$$, $$UPDATE$$) AND has_table_privilege(current_user, $$public.alert_dispatch_progress$$, $$DELETE$$), has_sequence_privilege(current_user, $$public.alert_dispatch_service_seq$$, $$USAGE$$)")).one()); print(r); sys.exit(0 if r == ("c4d8a2f6e193", 1, True, True, "on", True, True) else 1)'
   ```

   Expected output: `('c4d8a2f6e193', 1, True, True, 'on', True, True)` and a successful run. Any other output, any
   traceback or a non-zero exit is a **STOP**: connectivity, the credentials, the endpoint or the schema/privileges
   are not as required. Render's handling of a multi-line or quoted Docker Command is unverified: confirm that the
   command arrives intact (the printed tuple proves it) and never paste the output if it contains connection
   details. This check creates no new write path; the dispatcher itself is not run with processing enabled.
2. Only after 1b succeeded: read-only backlog check before the first effective run (counts only):
   `SELECT status, count(*), min(occurred_at) FROM financial_events GROUP BY 1;` Because the dispatcher executes
   AUTO rules and writes alerts for **all** users, decide knowingly how large a backlog the first run may meet.
   Optional cautious first run: `RULE_DISPATCHER_MAX_USERS=1`, `RULE_DISPATCHER_MAX_EVENTS_PER_USER=5`,
   `RULE_DISPATCHER_MAX_ALERT_USERS=5`, observed, then raise the limits.
3. Set `RULE_DISPATCHER_ENABLED=true` (keep the schedule). A manual "Trigger Run" cancels an active run and starts
   another: do not trigger manually while one is running.
**Unverified Render behaviour to confirm on the first deployment:** how a non-zero exit code (1, 2 or 3) appears,
whether failed-run notifications exist, and how to suspend the job.
**PASS:** the staged runs behave as stated. **STOP:** a non-zero exit in stage 1 or a failed stage 1b, `outcome: fatal`, or any
unexpected `progress_update_failures`. **Rollback:** set `RULE_DISPATCHER_ENABLED=false` (the next run exits 0
touching nothing), or delete the Cron Job. Committed events, executions and alerts are ordinary rows and need no
reversal; a half-done run leaves only expiring leases (up to 5 minutes).

## 12. Gate I - observed scheduled-run acceptance

**Entry:** Gate H stage 3 complete. **Duration:** at least until one full alert cycle has been observed, i.e.
`ceil(alert_users_total / alert_users_evaluated)` runs, and not less than the owner's chosen observation window.
**Acceptance criteria (all must hold):**

| Criterion | Evidence |
|---|---|
| runs happen on schedule and end with exit code 0 | Render run history |
| last line is `dispatcher_summary` with `outcome` `success` or `noop` | logs |
| `alert_selection: progress`, `alert_coverage: deterministic` | summary line (`random` means the E10 schema is missing or switched off) |
| `progress_update_failures`, `events_dead` and `user_failures` are 0 | summary line |
| back-to-back runs change nothing | the duplicate checks of rule-dispatcher.md section 4 return no rows; `alerts_created` is 0 on an unchanged state |
| the oldest due event stays under about 30 minutes (3x the schedule) | the backlog query of rule-dispatcher.md section 4 |
| no user is starved | `SELECT count(*) FROM alert_dispatch_progress WHERE last_success_at IS NULL OR last_success_at < now() - interval '2 hours';` is 0 after a cycle (counts only) |
| connections stay within the Supabase limit | provider dashboard |
| failure visibility works | a deliberate non-production-impacting check of how exit code 3 is shown, or log-based alerting is in place |

Only after all rows hold may AUTO and alerts be described as running unattended. Never describe alert coverage as
deterministic while a summary reports `alert_coverage: probabilistic`. **Recovery:** Gate H rollback.

Ad-hoc SQL in Gates H and I (the backlog, duplicate and progress queries) is production SQL too: run it only in a
read-only session, for example `PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' psql -X
-v ON_ERROR_STOP=1 -c '<query>'`, with counts only.

## 13. Authorizations the owner must give (nothing is implied)

| Gate | Authorization that must be given explicitly |
|---|---|
| A | read-only access to production diagnostics: the Render dashboard (read only) and the database through the read-only runner |
| B | creating and restore-verifying a logical dump of production, and where it may be stored |
| C | applying exactly `a7c3e91d5b24` to the named database in a stated window |
| E | the second read-only preflight and a fresh dump |
| F | applying exactly `c4d8a2f6e193` to the named database in a stated window |
| D | the E9A post-check, the authenticated application reads and the external Data API probe |
| G | the follow-up read-only checks and the external Data API probes |
| H | creating the Cron Job, its plan and recurring cost, the staged activation, any change to the web service environment |
| I | the read-only queries and dashboard observation of Gate I, and the backlog query of Gate H |
| any | a production downgrade, a backup restore, or deleting the Cron Job |

## 14. Current readiness (as of the commit that added this document)

| Item | Status |
|---|---|
| `main` `f28818b`, PR #96 merged, Backend CI success on that commit | VERIFIED |
| single Alembic head `c4d8a2f6e193`; chain `e0503e9ca9d3 -> a7c3e91d5b24 -> c4d8a2f6e193` | VERIFIED |
| local verification package (this document, runbooks, SQL, runner, tests) | VERIFIED on PostgreSQL 18.1 locally; PostgreSQL 16 in CI after merge; PostgreSQL 17 (production) not exercised |
| production revision, deployed SHA, Data API privileges, connectivity, historical HTTP 500 | UNKNOWN (Gate A) |
| E9A and E10 applied in production | UNKNOWN |
| Render Cron Job, its cost and notification behaviour | BLOCKED (Gates H, I) |

**The system is not ready for production activation.** The next required step is the owner's authorization of
Gate A.
