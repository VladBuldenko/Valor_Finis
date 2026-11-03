# Owner Input Register (VF-QA-1)

Every identifier below is needed to provision and verify staging. **Nothing here has been provided**: the status of every row is
`UNKNOWN` as of 2026-11-03, and no value is invented in this repository. A row moves to `PROVIDED` when the owner supplies it and to
`VERIFIED` only when the stated method has been run and its evidence stored. `BLOCKED` marks a row that cannot proceed for a
named reason. Values are never written in this file: identifiers go in the operator-held
[approved-targets file](approved-targets-spec.md) and secrets in the staging secret store.

Statuses: `UNKNOWN` / `PROVIDED` / `VERIFIED` / `BLOCKED`.

| ID | Required identifier | Purpose | Owner | Status | Verification method | Needed before provisioning? |
|---|---|---|---|---|---|---|
| OI-01 | Staging Supabase project reference | Allowlist match; `SUPABASE_URL` is derived from it | Owner | UNKNOWN | `identify` compares `SUPABASE_URL` with it; live probe accepts the staging key | Yes |
| OI-02 | Staging Supabase publishable key (secret-store reference only) | Backend Auth validation, mobile build | Owner | UNKNOWN | Live probe of the staging project returns 200 | Yes |
| OI-03 | Staging Supabase secret (service-role) key (secret-store reference only) | Receipt storage driver; creating the Auth users through the admin API | Owner | UNKNOWN | Not printed or logged; storage upload test on staging only | Only if storage driver is `supabase` or users are created by API |
| OI-04 | Where the staging PostgreSQL lives, and its database name | The roadmap requires a name ending `_staging`, but a hosted Supabase project's default database is named `postgres`. Decide: a second database `<name>_staging` on the staging project's server, or a separate PostgreSQL server | Owner | UNKNOWN | Owner decision recorded; `identify` shows the name | Yes (blocks everything below) |
| OI-05 | Database host and port (direct or session-mode endpoint, never the transaction pooler) | Allowlist host and port | Owner | UNKNOWN | `identify` connects and matches exactly | Yes |
| OI-06 | Application database role and credential (secret-store reference only) | `DATABASE_URL` | Owner | UNKNOWN | Not printed; connection succeeds with TLS `require` or stronger | Yes |
| OI-07 | PostgreSQL major version (17 preferred) | Match the production engine major per the ops notes; QA-2 covers PG16 and PG17 | Owner | UNKNOWN | `identify` prints the server major version | Yes (decision) |
| OI-08 | Database oid | Pins "this exact database", not just its name | Owner (from `identify`) | UNKNOWN | `CONNECTED_OID_MISMATCH` test; recorded after R3/R4 | After the empty database exists |
| OI-09 | Production denylist: database hosts | Refuse production by host | Owner | UNKNOWN | Loader requires at least one entry | Yes |
| OI-10 | Production denylist: Supabase project references | Refuse production by project | Owner | UNKNOWN | Loader requires at least one entry | Yes |
| OI-11 | Production denylist: database names | Refuse production by database name | Owner | UNKNOWN | Optional list | No |
| OI-12 | Owner approval (name, date) of each staging entry and of the denylist | Accountability for the identifiers | Owner | UNKNOWN | Fields `approved_by/on`, `recorded_by/on` present | Yes |
| OI-13 | Backend instance (own deployment or local container) and its environment name | Runs the API against staging only | Owner | UNKNOWN | Fingerprint of the API origin matches the QA-0 register | Yes |
| OI-14 | Receipt storage bucket (staging project) or `local` driver | Separate receipt storage | Owner | UNKNOWN | Upload of a synthetic receipt lands in the staging bucket only | Yes |
| OI-15 | Staging secret store and its access list | Holds every secret; no production overlap | Owner | UNKNOWN | Access list reviewed; no production credential present | Yes |
| OI-16 | Operators and written authorization per mutating run | Who may bootstrap, reset, seed | Owner | UNKNOWN | Authorization reference stored with the evidence record | Yes |
| OI-17 | Auth: email sign-up and confirmation behaviour | MF-4, J19 | Owner / QA-1 | UNKNOWN | Setting recorded in the [Auth checklist](supabase-auth-checklist.md) | Before MF-4 |
| OI-18 | Auth: SMTP provider for confirmation and recovery mail | MF-4, J19, J20 | Owner | UNKNOWN | A test message is received for each template | Before MF-4 |
| OI-19 | Auth: password policy | MF-4 validation copy | Owner | UNKNOWN | Setting recorded; behaviour observed | Before MF-4 |
| OI-20 | Auth: rate limits | MF-4, BR-7 drills | Owner | UNKNOWN | Settings recorded | Before MF-4 |
| OI-21 | Auth: redirect URL allowlist and the app-unique URL scheme | Recovery deep link (MF-4 chooses the scheme) | Owner | UNKNOWN (BLOCKED on MF-4) | Allowlist holds only staging entries; no generic `mobile://` | Before MF-4 |
| OI-22 | Auth: observed behaviour of sign-up with an existing address | Copy rule C6 (no account enumeration) | QA-1 operator | UNKNOWN | Observation recorded with the settings active | Before MF-4 |
| OI-23 | Auth user ids of QA-A and QA-B | The seed's users file; the seed never creates users | Owner | UNKNOWN (BLOCKED on OI-01, OI-02) | Users exist in the staging project; ids recorded outside the repository | Before seeding |
| OI-24 | Mobile QA build channel and installation method | Builds that target staging only | Owner | UNKNOWN | QA-0 fingerprint helper passes for the build | Before device runs |
| OI-25 | Physical devices (QA-0 matrix slots) | Device acceptance | Owner | UNKNOWN | See the [QA-0 device matrix](../../mvp/qa-device-matrix.md) | Before device runs |

## Items that are decisions, not values

- **OI-04** is a genuine architecture question the repository cannot answer: whether a database named `*_staging` can be created
  inside a hosted Supabase project (and whether the Data API hardening checks are then meaningful for that database) or whether
  staging uses a separate PostgreSQL server. Until the owner decides, the guard stays strict (`_staging` is mandatory) and no
  provisioning can start.
- **OI-07**: the roadmap prefers PostgreSQL 17 for staging while production's major is stated only as "per ops notes"; the owner confirms.
