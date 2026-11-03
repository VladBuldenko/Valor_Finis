# Approved-Targets Specification (VF-QA-1)

The staging identity guard compares every request with a file the **owner** controls. The file holds identifiers only (hosts,
project references, database names, one database oid). None of these is a secret, but they are never committed.

## 1. Rules for the file

- Stored **outside the repository working tree** (the loader refuses a path inside it: `CONFIG_LOCATION`). Typical place: the
  operator's secret store or `~/.config/valor-finis/`.
- Regular file, not writable by group or others (`chmod 600`): otherwise `CONFIG_PERMISSIONS`.
- Strict JSON: unknown or missing fields, malformed values and contradictions are refused (`CONFIG_MALFORMED`, `CONFIG_CONTRADICTORY`).
- Passed with `--approved-targets <path>`. It is never read from the environment, and no default path exists.
- Contains **no** password, key, token, connection string or URL. The tool takes credentials from the process environment only.

## 2. Shape

A placeholder example that the loader accepts is [approved-targets.example.json](approved-targets.example.json). **Its values are fake**;
the owner replaces every one. Fields:

| Field | Meaning | Rule |
|---|---|---|
| `schema_version` | Format version | exactly `1` |
| `staging[]` | Approved staging environments | at least one for any mutation |
| `staging[].id` | Entry id used with `--staging` | `STG-<number>`, unique |
| `staging[].database.host` | PostgreSQL host | lower-case host name or IP, exact match, no wildcard |
| `staging[].database.port` | PostgreSQL port | integer 1 to 65535; never the transaction-pooler port 6543 in practice |
| `staging[].database.name` | Database name | `[a-z][a-z0-9_]*`, ends `_staging` |
| `staging[].database.oid` | `pg_database.oid` of that database | **required for any mutation**; absent only until `identify` has been run |
| `staging[].supabase_project_ref` | Staging Supabase project reference | 10 to 40 lower-case letters or digits |
| `staging[].approved_by`, `approved_on` | Owner's name and ISO date | non-blank, valid date |
| `production_denylist.database_hosts[]` | Production database hosts | at least one; a host or any subdomain of it is refused |
| `production_denylist.supabase_project_refs[]` | Production Supabase project references | at least one |
| `production_denylist.database_names[]` | Production database names | may be empty |
| `production_denylist.recorded_by`, `recorded_on` | Owner's name and ISO date | non-blank, valid date |

A staging entry that overlaps the denylist (same host or subdomain, same project, same database name) makes the whole file invalid.
Hosts and project references on the denylist are identifiers of production; keep this file with the same care as other
operator material even though it contains no secret.

## 3. How the owner obtains the oid

1. Provision the empty staging database (name ends `_staging`).
2. Write the file **without** `oid` and run `identify` (read-only; it needs the full guard except the oid).
3. `identify` prints the database oid, server major version and whether the database is empty and unmigrated.
4. Add `oid` to the entry. From now on a different database that merely has the same name is refused (`CONNECTED_OID_MISMATCH`).

If the database is dropped and recreated, its oid changes; the owner repeats steps 2 to 4 deliberately.

## 4. What is checked against it

The guard chain and its refusal codes are in the [runbook, section 4](staging-architecture-and-runbook.md#4-the-identity-guard).
A suffix or an environment variable name is never sufficient: the host, port, database name, pinned oid, Supabase project and the
production denylist must all agree, and the identity is re-proved before the mutation.

## 5. Relationship to the QA-0 register

`docs/mvp/qa-evidence/staging-register.md` holds **fingerprints** that prove which environment a **mobile build** targets. This
file holds the identifiers the **database tools** compare. They serve different checks and are maintained separately; the owner
records the same staging environment in both. The database host fingerprint recorded in the QA-0 register may be taken from the
`host_fingerprint` field of a `staging_ops` evidence record (it is computed from `db-host:<host>:<port>`); the QA-0 helper does not
check that column.
