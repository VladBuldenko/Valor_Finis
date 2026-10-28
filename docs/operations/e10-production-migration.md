# E10 production migration runbook (`c4d8a2f6e193`, `alert_dispatch_progress`)

Status: **prepared, never executed.** Every step needs the separate written authorization named in
[financial-rules-production-release.md](financial-rules-production-release.md). Operator conventions (credentials,
endpoint, runner variables) are in [e9a-production-migration.md](e9a-production-migration.md) section 2 and apply
unchanged.

## 1. Facts about the migration (from the merged code)

| Item | Value |
|---|---|
| Revision / parent | `c4d8a2f6e193` / `a7c3e91d5b24` (E9A). It cannot be applied before E9A. |
| Creates | sequence `public.alert_dispatch_service_seq` (BIGINT, start 1, increment 1); table `public.alert_dispatch_progress` with exactly six columns (`user_id` uuid PK, `service_seq` bigint NOT NULL UNIQUE, `last_attempted_at` timestamptz NOT NULL default `now()`, `last_success_at` timestamptz NULL, `consecutive_failures` integer NOT NULL default 0, `last_error_code` varchar(64) NULL); two CHECKs (`consecutive_failures >= 0`; `last_success_at IS NULL OR last_success_at <= last_attempted_at`); index `ix_alert_dispatch_progress_last_success_at` |
| Foreign keys | none |
| Locks on existing tables | **none**: it references and changes no existing relation (only brand-new objects and catalog rows) |
| Existing data | not read, not changed, no backfill |
| Data API privileges | `REVOKE ALL PRIVILEGES` on the table **and** on the sequence from `anon`, `authenticated`, `service_role`, guarded by `pg_roles` |
| Who uses it | only the periodic dispatcher (and its tests). The web service never touches it. |
| Runtime compatibility | the dispatcher runs correctly **before and after** this migration: while the table is absent (or `RULE_DISPATCHER_ALERT_PROGRESS=off`) it uses the per-run random sample and reports `alert_selection: random`, `alert_coverage: probabilistic`. Apply the migration first, activate afterwards. |
| Downgrade | drops the index, the table and the sequence. No history guard: the rows are scheduling state only. Re-grants nothing. |

## 2. Gate E - read-only preflight and backup

```bash
cd docs/operations/sql
./run_readonly_check.sh e10_preflight <production_database_name>
```

**PASS requires, all at once:** a read-only session on the expected database; PostgreSQL >= 15; exactly one
`alembic_version` row equal to `a7c3e91d5b24`; `rule_alerts` present with its alert-key constraint;
`alert_dispatch_progress` and `alert_dispatch_service_seq` absent; no relation, constraint or type whose name
contains `alert_dispatch` in **any** schema (a partial earlier attempt); `CREATE` right on `public`; no
idle-in-transaction session, no transaction older than 5 minutes, no prepared transaction, no ungranted lock (and
the runner role can read all session statistics, otherwise those counts would be blind); the Data API roles exist.

**STOP** on any `FAIL`. STOP with revision `c4d8a2f6e193` means E10 is already applied: do not migrate, run the
post-check instead. STOP with revision `e0503e9ca9d3` means E9A is missing: E10 must not proceed.

**Backup:** take a **fresh** verified logical dump with the procedure of the E9A runbook section 4 (file name
`vf_e10_pre_<UTC>_rev_a7c3e91d5b24.dump`). Do not reuse the pre-E9A dump: after E9A the E9B runtime may have
written alerts, which that dump does not contain. Restore-verify it into a throwaway `*_test` database; the
restored copy must pass `e10_preflight` (`alembic_revision_is_e9a` OK; the table absent checks OK) with
`REQUIRE_DATA_API_ROLES=no` locally. Then write the receipt for the runner (E9A runbook section 4, with
`GATE_TARGET=c4d8a2f6e193` and `SOURCE_REVISION=a7c3e91d5b24`).

## 3. Gate F - the exact upgrade (authorization naming `c4d8a2f6e193`)

Use **only** the fail-closed runner described in the E9A runbook section 5 (same environment, same guards, same
exit codes). Do not type `alembic upgrade` by hand.

```bash
BACKUP_EVIDENCE_FILE="$RECEIPT" ./run_guarded_migration.sh c4d8a2f6e193 <production_database_name>
```

`$RECEIPT` is the receipt of the **fresh pre-E10 backup** (the format and rules are in the E9A runbook section 4, with
`GATE_TARGET=c4d8a2f6e193`, `SOURCE_REVISION=a7c3e91d5b24`, file name `vf_e10_pre_<UTC>_rev_a7c3e91d5b24`). The runner
refuses the pre-E9A receipt (wrong source revision), a dump without `rule_alerts`, and any evidence older than 24 hours.
Like every use of this runner it is never a bootstrap and never used for staging builds.

Here the runner requires `alembic current` to be exactly `a7c3e91d5b24`, `e10_preflight` to PASS, and after the
upgrade both `e10_postcheck` and `e9a_postcheck` to PASS (exit 13 otherwise). Although this migration takes no lock
on an existing relation, the timeouts stay: they bound any unexpected wait. Exit 11 means nothing was changed;
exit 12 means the single upgrade transaction failed and nothing was committed. No retry loop.

## 4. Gate G - post-check, role security and runtime compatibility

```bash
APP_ROLE=<the role in the production DATABASE_URL> ./run_readonly_check.sh e10_postcheck <production_database_name>
APP_ROLE=<the same role> ./run_readonly_check.sh e9a_postcheck <production_database_name>   # rule_alerts must stay correct and private
```

Both must PASS: `e10_postcheck` covers only the E10 objects, `e9a_postcheck` accepts the E10 revision and
re-verifies `rule_alerts`.

PASS means: revision exactly `c4d8a2f6e193`; the table is an ordinary permanent table with exactly the six
expected columns, types, nullability and defaults; exactly the four expected validated constraints (primary key on
`user_id`, `UNIQUE (service_seq)`, the two CHECKs) and **no** foreign key; exactly the three expected valid
indexes including the monitoring index; the sequence is `bigint`, start 1, minimum 1, maximum
9223372036854775807, increment 1, no cycle, cache 1; table and sequence have the same owner and it is not a Data
API role; the application role can SELECT/INSERT/UPDATE/DELETE the table and use the sequence (`nextval` needs
`USAGE`); **no effective** privilege for `anon`, `authenticated`, `service_role` on the table, its columns or the
sequence (privileges inherited through role membership, `PUBLIC` and superuser status all count); no `PUBLIC`
privilege on either object. INFO rows show the RLS state, the ACL grantee names and `0 / unused` (row count and
sequence last value).

Runtime compatibility: the deployed build contains the required commit **only if** it is a descendant of it, see
the SHA rule in the release document. Before activation the dispatcher must be able to report
`alert_selection: progress` on its first run; until a scheduled run shows that, do not call alert coverage
deterministic.

## 5. Stop conditions

A preflight or post-check that does not PASS; a wrong or duplicated revision; any pre-existing `alert_dispatch*`
object; open long transactions; a failed backup or restore; a lock timeout; any output that would expose a
credential or host.

## 6. Recovery and rollback limits

- **Failed upgrade:** rolled back; verify with the preflight and stop.
- **Post-check fails after a successful upgrade:** the objects are additive and only the dispatcher reads them.
  Leave them, set `RULE_DISPATCHER_ALERT_PROGRESS=off` on the cron job if it exists (it then ignores the table),
  report, decide separately.
- **Privilege exposure:** a guarded `REVOKE` on `public.alert_dispatch_progress` and
  `public.alert_dispatch_service_seq` for the named role in one transaction after separate approval, then repeat
  the post-check.
- **Downgrade (`alembic downgrade a7c3e91d5b24`) is not universally safe while workers are active:** it drops the
  table and the sequence. A dispatcher run that started earlier can then fail every progress write
  (`progress_update_failures`, a circuit-breaker exit) until it ends. Therefore, in this order: set
  `RULE_DISPATCHER_ALERT_PROGRESS=off` (or `RULE_DISPATCHER_ENABLED=false`), wait until no run is active, then
  downgrade under the same `PGOPTIONS`. The service order is lost, which is harmless: it rebuilds itself and the
  fallback is the random sample.
- A backup restore is for catastrophic loss only and needs its own decision.

## 7. Validation evidence (local, disposable databases only)

Same test module as the E9A runbook. For E10 it checks: the preflight passes at E9A, refuses a database at
`e0503e9ca9d3`, a database that already has E10, and five kinds of partial objects (sequence only, table only, a
misnamed index, an object in another schema, a type), an idle-in-transaction session and missing Data API roles; the
post-check passes after the real migration, with a dedicated application role and private Data API roles, and
detects thirteen kinds of schema drift (dropped or altered constraints, an added unvalidated constraint, a
missing index, an extra or retyped column, a dropped default, a cycling, stepped or cached sequence), a foreign
key that should not exist, split or Data-API-role ownership, a missing application grant, and eight kinds of
effective Data API exposure on table or sequence (direct, inherited through a parent role, `PUBLIC`,
column-level, superuser). Production-equivalent PostgreSQL 17 has not been exercised (see the E9A runbook).
