# Provisioning and Acceptance Checklist (VF-QA-1)

Two separate gates. Do not report the second one from the first.

> **Reduced-scope staging foundation (owner-approved scope change, 2026-11-04).** The automatic reset is **DISABLED / DEFERRED**, so the original full
> QA-1 exit criteria are not satisfied. Bootstrap and seed are READY as implementation only. Hosted staging is NOT PROVISIONED, Supabase Auth
> integration is NOT VERIFIED, PostgreSQL 17 hosted verification is NOT RUN, Data API parity is NOT VERIFIED, and BR-5, BR-7 and BR-12 are NOT COMPLETE.

## A. Implementation readiness (scripts and tests; reviewable now)

Status "VERIFIED LOCALLY" means the command was run on 2026-11-03 against local resources only (no cloud service, no remote database).
Commands run from `services/api` with a **disposable local PostgreSQL** whose database is named `*_test` for the harness
(`DATABASE_URL=postgresql://<user>@localhost:<port>/valor_test`, as in CLAUDE.md).

| ID | Check | Command or evidence | Status |
|---|---|---|---|
| IR-1 | Identity guard negative tests (every listed refusal; the mutation command is never invoked) | `.venv/bin/python -m pytest tests/unit/staging_tooling -q` | VERIFIED LOCALLY |
| IR-2 | Bootstrap, binding, the disabled reset (refuses, nothing changes), seed (serialization, crash and retry) and the operator-check scripts against a real disposable PostgreSQL | `.venv/bin/python -m pytest tests/integration/staging_tooling -q` (skips as `NOT RUN` without server binaries) | VERIFIED LOCALLY (PostgreSQL 18, local cluster started by the test) |
| IR-3 | Negative controls: removing a critical guard makes a test fail; equivalent and invalid mutants reported separately | [negative-controls.md](negative-controls.md) | VERIFIED LOCALLY |
| IR-4 | Full backend regression | `.venv/bin/python -m pytest -q` against `valor_test` | VERIFIED LOCALLY |
| IR-5 | Single Alembic head | `.venv/bin/alembic heads` | VERIFIED LOCALLY |
| IR-6 | No secret or hosted identifier in the staging files | `tests/unit/staging_tooling/test_repository_hygiene.py` | VERIFIED LOCALLY |
| IR-7 | Production guarded runner unchanged; Alembic hook inert without `VF_STAGING_BINDING` | hygiene tests; `git diff` of `docs/operations/sql/` is empty | VERIFIED LOCALLY |
| IR-8 | Not executed against any real endpoint | by construction: Supabase probe injected in every test; approved-targets file must be outside the repo | VERIFIED LOCALLY |

## B. Operational staging readiness (the environment exists and is independently verified)

None of these has been done. All depend on [owner inputs](owner-input-register.md).

| ID | Check | Evidence required | Status |
|---|---|---|---|
| OR-1 | Separate Supabase project, PostgreSQL, backend, storage, secret store, operators | Owner confirmation, access list | BLOCKED (OI-01 to OI-16) |
| OR-2 | Approved-targets file written outside the repository and reviewed by the owner | File reviewed, `approved_by/on` present | BLOCKED |
| OR-3 | `identify` shows an empty, unmigrated database; oid recorded | Evidence record | NOT RUN |
| OR-4 | `bootstrap` built the database to head; `alembic current` equals `alembic heads` | Evidence record (`alembic_head` equals `alembic_current`) | NOT RUN |
| OR-5a | A1 application database security checks pass on the staging application database (`run_staging_check.sh app_database_security`) | Runner output (verdict rows and counts only); keep the `DATA_API_PARITY: NOT VERIFIED` line | NOT RUN |
| OR-5b | B1 staging Supabase project database is a real Supabase project database (three Data API roles and `auth` schema, gating) and holds no application relation or function in `public` (`run_staging_check.sh supabase_project_exposure`), and the B2 Data API listing is recorded | Runner output and the recorded listing | NOT RUN (architecture A) |
| OR-5c | B3 Data API parity with production hardening | Cannot be produced on architecture A. Reported **NOT VERIFIED** with the justification in the [runbook section 6.1](staging-architecture-and-runbook.md#61-operator-checks-application-database-a-versus-supabase-data-api-b). Never recorded as PASS from a database without the real Supabase roles | NOT VERIFIED |
| OR-6 | Auth settings recorded ([checklist](supabase-auth-checklist.md)), test emails received | Filled checklist | BLOCKED (OI-17 to OI-22) |
| OR-7 | QA-A and QA-B created in the staging project; users file written outside the repository | Owner confirmation | BLOCKED (OI-23) |
| OR-8 | `seed` completed; a second `seed` changed nothing | Two evidence records | NOT RUN |
| OR-9 | ~~A reset rehearsal on staging~~ **DEFERRED** (the reset is disabled; owner-approved scope change). Not required for the reduced-scope foundation | None | DEFERRED |
| OR-10 | Mobile QA build passes the QA-0 fingerprint helper; QA-0 register filled by the owner | `artifacts/staging-fingerprint.txt`, register entry | NOT RUN |
| OR-11 | One end-to-end sign-in from a device build against staging only | QA-0 evidence row | NOT RUN |
| OR-12 | A scan shows no production identifier in the repository's staging configuration | Scan output | NOT RUN |
| OR-13 | No production credential present in the staging secret store or shells | Owner confirmation | NOT RUN |

## Gate status after QA-1 (unchanged)

| Gate | Status | Why |
|---|---|---|
| BR-5 device acceptance | FAIL (none) | No device run exists; staging is not provisioned |
| BR-7 session and timeout drills | FAIL (none) | Needs staging and MF-2/MF-3 builds |
| BR-12 rules end to end on staging | FAIL (none) | The seed supplies the scenarios; the staging scenario script and its database assertions have not run |

## Hand-offs

- **QA-2** (guarded-runner rehearsals from exact revisions with data, PG16 and PG17): needs an explicit-revision bootstrap mode behind the same guard.
- **MF-4**: needs OR-6 and the facts F1 to F11 of the Auth checklist.
- **QA-3 / QA-4**: need OR-8 and OR-10.
