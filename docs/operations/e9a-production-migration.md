# E9A production migration runbook (`a7c3e91d5b24`, `rule_alerts`)

Status: **prepared, never executed.** Every step needs the separate written authorization named in
[financial-rules-production-release.md](financial-rules-production-release.md). Nothing here may be run against
production on the strength of this document alone. The scripts were validated only on disposable local
databases (see "Validation evidence").

## 1. Facts about the migration (from the merged code, not assumed)

| Item | Value |
|---|---|
| Revision / parent | `a7c3e91d5b24` / `e0503e9ca9d3` (E6 execution schema) |
| Creates | table `public.rule_alerts` (11 columns), 9 constraints (pkey, composite FK to `financial_rules(id, user_id)` with `ON DELETE SET NULL (rule_id)`, `uq_rule_alerts_alert_key`, 6 CHECKs), 4 indexes besides the pkey index (see post-check), nothing else |
| PostgreSQL requirement | 15 or newer (`SET NULL (column list)`); production is 17.x |
| Lock on existing tables | `LOCK TABLE financial_rules IN SHARE ROW EXCLUSIVE MODE` for the whole (sub-second) transaction. Reads continue; INSERT/UPDATE/DELETE on `financial_rules` wait. The migration sets **no** lock timeout itself: the operator must. |
| Existing data | not read, not changed, no backfill |
| Data API privileges | `REVOKE ALL PRIVILEGES ON TABLE rule_alerts` from `anon`, `authenticated`, `service_role`, guarded by a `pg_roles` existence check |
| Transactions | one transaction (transactional DDL): a failure or a lock timeout commits nothing |
| Downgrade | locks `financial_rules` and `rule_alerts` in ACCESS EXCLUSIVE mode, **refuses if any alert row exists**, drops the indexes and the table. It re-grants nothing. |

Why the lock timeout matters: a pending `SHARE ROW EXCLUSIVE` request queues behind running writers and every
newer writer then queues behind it. An unbounded wait can therefore stall the application. A short
`lock_timeout` turns "busy table" into a clean, retryable failure.

## 2. Operator conventions (all gates)

- Credentials come only from the libpq environment (`PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, and `PGPASSWORD`
  or `PGPASSFILE`) loaded from the owner's approved secret store into the operator's own shell.
  `PGSERVICE`, `PGSERVICEFILE` and `PGHOSTADDR` must not be set: libpq lets them override the host, TLS mode and
  options that the runner validates (the runner refuses to start with any of them).
  Never put a secret in an argument, a command line, a file inside the repository, a chat message, a ticket or a
  log. Do not enable shell tracing. Do not paste raw error output that may contain a host name.
- Use the **direct or session-mode** database endpoint (port 5432) for the checks and for Alembic. A transaction
  pooler (typically port 6543) rejects the startup options these procedures rely on and is not suitable for DDL.
  Which endpoint the Render service uses is a Gate A finding. Prefer `PGSSLMODE=verify-full` with the provider's CA
  certificate (`PGSSLROOTCERT`) over `require`, which does not verify the server.
- The read-only runner is [`sql/run_readonly_check.sh`](sql/run_readonly_check.sh). Set `APP_ROLE` to the role in
  the production `DATABASE_URL` (the API and dispatcher role: the database **role name**, for example `postgres`, not a pooler login such as `postgres.<project>`). Leave `REQUIRE_DATA_API_ROLES` at its default
  (`yes`): the Data API roles must exist in production, otherwise a privilege check would be vacuous.
- Save every runner output. Counts only appear in it; there are no customer rows.

## 3. Step 1 - read-only preflight (authorization A)

```bash
cd docs/operations/sql
./run_readonly_check.sh e9a_preflight <production_database_name>
```

**GO only if** the last line is `RESULT: PASS (e9a_preflight)`. The PASS means, all at once: read-only session;
the expected database; PostgreSQL >= 15; exactly one `alembic_version` row equal to `e0503e9ca9d3`; every
prerequisite table and `uq_financial_rules_id_user_id` present; **no** `rule_alerts` object, partial object,
constraint or type in any schema; `CREATE` right on `public`; no idle-in-transaction session, no transaction older
than 5 minutes, no prepared transaction, no ungranted lock, and no session holding a lock on `financial_rules`
that would conflict with the migration; the Data API roles exist.

Keep the `row_count:*` rows: they are compared with the post-check.

**STOP** on any `FAIL` row or a non-PASS result. That includes `runner_can_see_all_sessions`: if the connected
role cannot see other users' sessions the concurrency rows would be blind, so the check fails closed. Fix it by
using a role that may read all session statistics (membership in `pg_read_all_stats`, which needs the owner's
authorization); there is no override.
`STOP` with revision `a7c3e91d5b24` means E9A is already applied: do not migrate, go to the post-check (Gate D).

## 4. Step 2 - backup and restore verification (authorization B)

Backup requirement: a **logical dump taken now, verified by an actual restore**. Provider snapshots or PITR are
additional protection only; their state is UNKNOWN until checked in the Supabase dashboard and they do not replace
this step.

```bash
umask 077
BACKUP_DIR=<encrypted location outside the repository>
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$BACKUP_DIR/vf_e9a_pre_${STAMP}_rev_e0503e9ca9d3.dump"
pg_dump --format=custom --schema=public --file="$FILE"          # connection from PG* variables only
shasum -a 256 "$FILE" > "$FILE.sha256" && shasum -a 256 -c "$FILE.sha256"
pg_restore --list "$FILE" | head -n 40        # must list financial_rules, rule_executions, alembic_version
```

`pg_dump` must be at least as new as the server (production 17.x). The dump holds customer data: encrypt it at
rest, restrict access, never commit, attach or upload it, and delete it according to the owner's retention rule.

Restore validation on a **throwaway local database whose name ends in `_test`** (never production). Run it in a
**fresh subshell that first removes every production connection variable**, so it cannot reach the production
server by accident (`createdb` and `pg_restore` write to whatever server the variables name):

```bash
( set -e
  unset PGPASSWORD PGPASSFILE PGPASSCOMMAND PGSERVICE PGSERVICEFILE PGHOSTADDR PGOPTIONS PGSSLMODE PGSSLROOTCERT \
        PGSSLCERT PGSSLKEY PGTARGETSESSIONATTRS PGDATABASE DATABASE_URL
  export PGHOST=localhost PGPORT=5432 PGUSER="<local superuser name>"      # the LOCAL server and its own credentials
  # Prove the target really is this machine before anything is created or restored:
  case "$(psql -X -Atc "SELECT coalesce(host(inet_server_addr()), 'socket')" postgres)" in
      127.0.0.1|::1|socket) ;;
      *) echo "not a local server: aborting" >&2; exit 1 ;;
  esac
  createdb vf_restore_verify_test
  trap 'dropdb --if-exists vf_restore_verify_test' EXIT      # the throwaway copy never outlives this subshell
  # --clean --if-exists: the new database already has an empty `public` schema that the dump recreates
  pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname=vf_restore_verify_test "$FILE"
  PGDATABASE=vf_restore_verify_test REQUIRE_DATA_API_ROLES=no PGSSLMODE=disable ALLOW_INSECURE_LOCAL_TEST=1 \
    ./run_readonly_check.sh e9a_preflight vf_restore_verify_test )
```

The local server must be at least as new as the dump's server major version (a PG 17 dump can fail to restore on
PG 16). `--schema=public` covers the application tables and `alembic_version`; it does **not** contain the
`auth` and `storage` schemas (accounts, receipt files) or roles, and `--no-acl` on restore drops the ACLs, so a
real disaster recovery needs those from the provider's own backups. This dump is a verified application-data
backup, not a full-project backup.

**Receipt for the runner.** Only after the restore verification above PASSed (in the same shell session, so `FILE` and
`STAMP` are still set), write the receipt the guarded runner demands. It holds identifiers, hashes and timestamps, no
secret. Write `PASS` only for things you actually did; the runner re-verifies the dump itself (existence, SHA-256, readable
`pg_restore --list` with the required tables, age) but **cannot** re-perform the restore, so the `RESTORE_*` fields are
your attestation:

```bash
RECEIPT="$BACKUP_DIR/vf_e9a_pre_${STAMP}.receipt.env"
cat > "$RECEIPT" <<EOF
GATE_TARGET=a7c3e91d5b24
DATABASE=<production_database_name>
SOURCE_REVISION=e0503e9ca9d3
DUMP_FILE=$FILE
DUMP_SHA256=$(shasum -a 256 "$FILE" | cut -d' ' -f1)
DUMP_TAKEN_AT_UTC=$STAMP
RESTORE_VERIFIED=PASS
RESTORE_DATABASE=vf_restore_verify_test
RESTORE_PREFLIGHT=PASS
RESTORE_VERIFIED_AT_UTC=$(date -u +%Y%m%dT%H%M%SZ)
EOF
chmod 600 "$RECEIPT"
```

The runner accepts the receipt only if every field is present exactly once, it is bound to this target, database and
source revision, the restore database is a throwaway `*_test` database other than the target, the dump is a private
(mode 600) regular file owned by the operator, and both the dump and the restore verification are **younger than 24
hours** (otherwise take and verify a fresh backup).

**PASS:** the dump is non-trivial, the checksum verifies, the restore completes without errors, and the restored
copy passes `e9a_preflight`, and its `row_count:*` rows equal the production counts **at dump time**. Production is
live: if users wrote between the preflight and the dump, small differences are expected. Take the production
counts immediately before the dump, explain every difference by traffic in that gap, and when a core table
(`financial_rules`, `rule_executions`, `goal_transactions`) differs unexplainedly, repeat in a quieter moment
(or take the counts and the dump from one snapshot with `pg_dump --snapshot`). Never wave a difference through.
**STOP:** any mismatch, restore error, missing table or unverifiable checksum.

## 5. Step 3 - the exact upgrade (authorization C, naming `a7c3e91d5b24`)

Use **only** the fail-closed runner. Do not type `alembic upgrade` by hand and do not assemble the steps yourself.
With the libpq `PG*` variables (the same ones the preflight used) and `DATABASE_URL` loaded from the secret store
into the operator's shell (no echo), from `docs/operations/sql`:

```bash
BACKUP_EVIDENCE_FILE="$RECEIPT" ./run_guarded_migration.sh a7c3e91d5b24 <production_database_name>
```

The runner moves one existing database between two exact revisions; it is **never a bootstrap** (an empty or unmigrated
database is refused) and staging databases are built by the separate staging-only procedure
(`docs/mvp/mvp-ops03-and-staging-prerequisites.md` section 2.5). The runner applies exactly the named revision and **never reaches `alembic upgrade` unless every guard passed**.
There is no override flag. In this order it requires:

1. a valid environment (`PGSERVICE`, `PGSERVICEFILE`, `PGHOSTADDR` refused; `PGDATABASE` equal to the expected name; `psql`, `pg_restore` and `BACKUP_EVIDENCE_FILE` present; TLS required for both connection paths, so a `DATABASE_URL` with `sslmode` disable, allow or prefer is refused; `MIGRATION_PYTHON` is refused: it exists only for disposable local test databases);
2. **backup evidence** (section 4 receipt): bound to this target, database and source revision, the dump re-verified
   by SHA-256 and `pg_restore --list`, dump and restore verification younger than 24 hours (no database is contacted
   for this check);
3. an **endpoint proof**: the `PG*` path and the `DATABASE_URL` path must return the identical fingerprint (database
   oid, postmaster start time, database name, role) and both must report `lock_timeout = 5s` and
   `statement_timeout = 1min`. A different server or database, or an endpoint that dropped the startup options (some
   poolers do), stops the run;
4. `alembic current` reporting exactly the parent revision `e0503e9ca9d3` (the target already applied, a database
   ahead of it, or no output all stop the run);
5. the read-only `e9a_preflight` returning PASS (so every prerequisite, absence, lock and session check passed);
6. the endpoint proof and `alembic current` **repeated immediately before the upgrade**: the proof must equal the first
   one (same server instance) and the revision must still be exactly the parent (this narrows, but cannot remove, the
   window between check and change; the upgrade is a single transaction);
7. only then `alembic upgrade a7c3e91d5b24` under `lock_timeout` 5 s and `statement_timeout` 60 s;
8. the read-only `e9a_postcheck` returning PASS.

| Exit | Meaning | Action |
|---|---|---|
| 0 | migrated and verified | continue with Gate D evidence |
| 11 | **stopped before any migration; nothing changed** (a guard failed, the cause is printed) | fix the cause, re-run from the preflight |
| 12 | `alembic upgrade` itself failed (one transaction: nothing committed) | verify with the preflight, report, stop |
| 13 | migrated, but a post-check did not PASS | report; do not retry; see section 8 |
| 64 | refused to start (usage or unsafe environment) | fix the invocation |

Never retry in a loop and never raise a timeout to make a step pass. Do not interrupt the process after it started
the DDL; it is one transaction. Do not paste Alembic or runner output that may contain connection details (the
runner prints none). Whether a given Supabase endpoint honours startup options is not verified here: the endpoint
proof is what decides, per endpoint. Use the direct or session-mode endpoint for both `PG*` and `DATABASE_URL`.

## 6. Step 4 - post-migration verification (Gate D)

```bash
./run_readonly_check.sh e9a_postcheck <production_database_name>
```

PASS means: revision `a7c3e91d5b24` (or the later `c4d8a2f6e193`, which this check also accepts so `rule_alerts` stays verifiable after E10); `rule_alerts` is an ordinary permanent table with exactly the 11
columns, types, nullability and defaults; exactly the 9 expected validated constraints; the foreign key nulls
only `rule_id`; exactly the 5 expected valid indexes; no `rule_alert*` sequence; the owner is not a Data API
role; the application role can SELECT/INSERT/UPDATE/DELETE; **no effective** privilege for `anon`,
`authenticated`, `service_role` (table, columns, superuser flag, inherited through role membership) and none for
`PUBLIC`. Direct grants are not the criterion: effective privileges are. The exposure check does not rely on a list of
privilege names: any ACL entry held by a Data API role, or by a role it is a member of (with or without INHERIT),
fails, so privilege types added by newer PostgreSQL versions (such as `MAINTAIN` in 17) are covered. Constraint
comparison ignores parentheses, so drift that changes only AND/OR grouping inside a CHECK would not be seen. Compare the `row_count:*` rows with the
preflight (they must be equal; `rule_alerts` is 0 before the E9B runtime writes any alert).

Application validation (authenticated, by the operator): `GET /health`, `GET /api/v1/accounts`,
`GET /api/v1/financial-rules`, and, if the deployed build contains E9B, `GET /api/v1/rule-alerts`. The first
unauthenticated external check: a request to the Supabase Data API for the table with the public key must not
return data (expect 401/403/404, never a 200 JSON list).

## 7. Stop conditions (any one halts the procedure)

A preflight or post-check that does not PASS; a revision other than the documented one or more than one
`alembic_version` row; PostgreSQL older than 15; any pre-existing `rule_alerts` object; open long transactions or
waiters on `financial_rules`; a failed or unverified backup or restore; a lock timeout; any output that would
reveal a credential or host (stop and do not paste it).

## 8. Recovery and rollback limits

- **Failed or timed-out upgrade:** rolled back as one transaction. Verify revision and absence with the
  preflight, then stop and report.
- **Succeeded but the post-check fails:** the table is additive and only the E9B runtime reads it. Leave it in
  place, report, and decide separately. Do not restore the backup for a table-only problem.
- **Privilege exposure found:** a guarded `REVOKE` for the named role on `public.rule_alerts` in one transaction,
  after separate approval, then repeat the post-check.
- **Downgrade** (`alembic downgrade e0503e9ca9d3`) is **not** a universally safe lever:
  1. It takes `ACCESS EXCLUSIVE` on `financial_rules`, which blocks every read and write on that table until it
     finishes; run it only under the same `PGOPTIONS` timeout, in a quiet window.
  2. It refuses (by design) once any alert exists: alert history is never destroyed silently. Once the E9B
     runtime has written alerts, downgrade is unavailable without a separate, explicit data decision.
  3. While the web service or the dispatcher is running E9B code, the missing table is tolerated (the alert
     phase reports `alerts_unavailable`), but a run that started before the drop can fail mid-run. Stop or
     disable the dispatcher and let any active run finish first.
- A restore from backup is only for catastrophic data loss, discards all writes since the dump, and needs its
  own explicit decision.

## 9. Validation evidence (local, disposable databases only)

`services/api/tests/integration/financial_rules/test_release_verification_sql.py` runs the real Alembic chain on
throwaway `*_test` databases and checks: the preflight passes at `e0503e9ca9d3` and stops on a wrong revision,
duplicate revision rows, a partial object (including another schema), a missing prerequisite, a conflicting lock
and a wrong database; the post-check passes after the real migration and detects a dropped constraint, a wrong
foreign-key action, a dropped index and four kinds of effective Data API exposure (direct, inherited through role
membership, `PUBLIC`, column-level); the scripts contain no write statement, run in a read-only rolled-back
transaction and leave the schema, rows, ACLs and sequence values unchanged; the guarded runner (see section 5) stops with exit 11 and **never invokes `alembic upgrade`** on a `PG*`/`DATABASE_URL`
mismatch, a dropped lock timeout, an unexpected current revision, a failed preflight prerequisite, a conflicting
lock or an unreachable server, leaving schema and revision unchanged; it exits 12 when the upgrade fails and 13 when a
post-check fails; it refuses unsafe invocations before running anything. The restore-verification block above was executed as written against a locally made dump (restore, preflight PASS,
throwaway database removed). PostgreSQL 18.1 locally; the same tests run on PostgreSQL 16
in CI after merge. PostgreSQL 17 (production) has not been exercised: its constraint text could differ, which
would produce a **false STOP**, never a false PASS.
