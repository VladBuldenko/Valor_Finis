# QA Evidence Structure and Staging Isolation (QA-0)

Date: 2026-11-03. Basis: `main` @ `8bb98fb4ae07602825a9f44b8ada5561947ef913`.
Used by: [qa-device-acceptance-template.md](qa-device-acceptance-template.md),
[qa-security-regression-procedures.md](qa-security-regression-procedures.md), [qa-device-matrix.md](qa-device-matrix.md).
Gates served: BR-5, BR-6, BR-7, BR-8, BR-12 of [mvp-readiness-gates.md](mvp-readiness-gates.md).

Nothing here has been executed. No staging environment exists yet (QA-1), so no run record, fingerprint or waiver has been
created. The registers named below are committed **empty** on purpose.

## 1. Principles

1. **Staging only.** No physical device test targets production. No production URL, key, token, user or data appears in
   any run record, fixture, screenshot or log.
2. **No secrets in Git.** Never commit an auth token, refresh token, publishable or service-role key, database
   connection string, password, signed URL or unredacted log. Documents list variable **names** only.
3. **Synthetic data only.** Test users are team-controlled addresses; receipts are synthetic images; nothing is copied
   from a customer or from production.
4. **Evidence or it did not happen.** A result without an evidence file is `NOT RUN`, not `PASS`. A statement about a
   database (row counts, `alembic current`) is made only with an authorized assertion record (section 6). Otherwise
   the report says "app-observed only".
5. **Simulators and exports are not device acceptance.** A simulator, an emulator, an Expo export or a Node test may be
   recorded as supporting evidence, never as the physical-device `PASS` that BR-5 requires.

## 2. Directory layout

```text
docs/mvp/qa-evidence/
├── staging-register.md        owner-approved staging fingerprints and the production denylist (fingerprints only)
├── waivers.md                 owner-signed waiver register (committed empty)
└── <run-id>/                  one directory per run, created by copying the templates
    ├── run-record.md          metadata (section 4)
    ├── acceptance.md          copy of qa-device-acceptance-template.md with results filled in
    ├── procedures.md          copy of the SP results table from qa-security-regression-procedures.md
    ├── defects.md             defect register (section 7)
    ├── signoff.md             owner sign-off (section 8)
    └── artifacts/             screenshots, screen recordings, redacted logs, assertion records
        └── <row-id>-<nn>-<slug>.<ext>      for example ACC-IOS-J07-02-floor-warning.png
```

- **Run ID** format: `QA4-YYYYMMDD-NN` (task, date, sequence), for example `QA4-20261120-01`. A re-run is a new run ID;
  an existing run directory is never rewritten after sign-off. A correction is a new commit that adds a note, not an edit
  of a recorded result.
- Large video files are not committed. Store them in the team's evidence storage and record only a reference and a
  SHA-256 in `artifacts/`.
- Committed evidence files must pass section 5 before commit.

## 3. Staging isolation evidence

### 3.1 What does not prove the environment

- `GET /health` returns only `{"status","service","version"}` (`services/api/app/main.py`), identical in every
  environment. Reachability of `/health` proves nothing about which environment answered.
- The app shows no environment banner. `EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_SUPABASE_URL` and
  `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` are read at build time (`apps/mobile/src/config/env.ts`) and inlined into the
  JavaScript bundle, so what the bundle targets is decided when it is built or bundled, not when it runs.
- A tester's belief ("I used the staging link") is not evidence.

### 3.2 Fingerprint check (required for every run)

The person who builds or bundles the app runs the helper **with the same environment** that was used for the build:

```bash
node tools/qa/staging-fingerprint.mjs --register docs/mvp/qa-evidence/staging-register.md --staging STG-1
```

It reads only `EXPO_PUBLIC_API_URL` and `EXPO_PUBLIC_SUPABASE_URL`, and reports for each:
a one-way **origin fingerprint** (`fp1:` plus the first 16 hex characters of SHA-256 of the lower-cased
`scheme://host[:port]`, default ports removed) and whether it matches the named staging entry. For the publishable key it
reports only `set` or `not set`. It never prints the URL path, a query string, a credential in the URL or any key
value. It exits non-zero when: a variable is missing; a value is not an `https` URL (a local `http` URL is refused for
physical-device runs); a fingerprint matches any entry of the **production denylist**; or a fingerprint does not equal the named
`ACTIVE` staging entry; or the register holds no owner-approved production denylist entry (without one, a staging match
does not rule production out). The output is saved as `artifacts/staging-fingerprint.txt` and linked from `run-record.md`.

The register (`qa-evidence/staging-register.md`) holds fingerprints, not hostnames. Fingerprints are not secrets; they let a
reviewer confirm a match without the repository ever naming an endpoint. The **owner** approves each staging entry and
records the production denylist entries. Until the owner does, the helper has nothing to match and every run is
`NOT VERIFIED` (below).

### 3.3 Corroboration on the device (supporting, not sufficient alone)

1. Sign in as the seeded marker user QA-A. The user exists only if the QA-1 staging seed created it in the staging
   Supabase project; a successful sign-in with a seed-only account is consistent with, not proof of, the staging project.
2. Confirm the seed marker data is present (an Account named `QA-SEED-<staging-id>` created by the QA-1 seed).
3. If the operator is authorized to read staging, record `alembic current` of the staging database as an assertion
   record (section 6) and compare it with the backend commit's `alembic heads`.

### 3.4 Required statement in every run record

One of these two lines, copied verbatim into `run-record.md`:

- `Staging isolation: VERIFIED. Fingerprint check <artifact path> matched <STG id>; corroboration <list>.`
- `Staging isolation: NOT VERIFIED. <reason>.` A run with this line cannot produce a `PASS`; the validator rejects any
  `PASS` row whose run record carries it.

### 3.5 Prohibitions

- Never contact production to prove that a fingerprint is not staging. The denylist is matched offline.
- Never add a production endpoint, project reference or credential to the register, a fixture, a screenshot or a log.
  The denylist stores fingerprints, never the value that produced them.
- If a production fingerprint is ever matched, stop the run, record a Sev-1 defect, rotate nothing yourself, and tell the owner.

## 4. Run record fields

`run-record.md` is a two-column table with exactly these fields:

| Field | Content |
|---|---|
| Run ID | per section 2 |
| Gate and scope | for example `BR-5, J01–J20, iOS and Android` |
| App commit SHA | full 40 hex characters of the commit the build was made from |
| Backend commit SHA | full 40 hex characters of the deployed staging backend |
| Backend migration head | `alembic heads` output of the backend commit; the live database revision only with an assertion record |
| App version | `expo.version` from `app.json` at the app commit |
| Build type | one of `expo-go`, `development-build`, `internal-release` (matrix section 6) |
| Build channel | for example `local-lan`, or the EAS channel name once one exists |
| Installation method | how the build reached the device (matrix section 6) |
| Staging environment identifier | an `ACTIVE` entry of the staging register |
| Staging isolation line | one of the two lines in section 3.4 |
| Devices | model, exact OS, role (reference / secondary), physical or simulated |
| Network profile | Wi-Fi, constrained, airplane-mode steps used |
| Accessibility settings | screen reader, text scale, reduce motion, as used |
| Test users | aliases only (QA-A, QA-B); never addresses or passwords |
| Tester | name or handle |
| Started and finished | ISO 8601 timestamps |
| Owner sign-off | link to `signoff.md` |

## 5. Redaction and what must never be committed

Forbidden in any committed QA file (the validator scans for the patterns marked *scanned*):
- bearer or refresh tokens, JWTs (`eyJ…`) *scanned*
- Supabase publishable or secret keys (`sb_publishable_…`, `sb_secret_…`), `service_role` values *scanned*
- database connection URLs that embed a user name and password *scanned*
- hostnames of Supabase projects, Render services or other hosted back ends (`*.supabase.co`, `*.onrender.com`) *scanned*
- real email addresses (use aliases QA-A, QA-B; example domains `example.test` or `example.invalid` are allowed)
- passwords, one-time codes, recovery links, signed storage URLs
- screenshots showing a dev menu, a LAN IP with a port, the OS notification shade with personal content, or any real person's data
- unredacted device logs (`adb logcat`, Xcode device console)

How to redact: crop or blur before saving; replace values in text logs with `<redacted>`; keep only the lines that prove the
step. If a secret is committed by mistake, stop, tell the owner, and treat the secret as compromised; deleting it in a
later commit is not enough.

## 6. HTTP and database assertions

App-level behavior (what the screen shows, which request the app sends) is observed on the device and is the default evidence.
**Backend or operational assertions** (HTTP replay with a token, SQL against staging) happen only when:
1. the owner authorized them for this run, in writing, referenced in `run-record.md`;
2. the target equals the `ACTIVE` staging entry (fingerprint check passed);
3. they are read-only (`SELECT`, `alembic current`, `alembic heads`);
4. the operator, not the tester's personal credentials, runs them.

Each assertion is saved as `artifacts/assert-<nn>-<slug>.md` with: assertion purpose, the exact read-only statement or
request (credentials and tokens omitted), the environment identifier, the observed result, the operator, and the
authorization reference. A statement such as "one row exists" or "row count unchanged" is allowed in a report only when
such an assertion record exists. Without one the report says "app-observed only".

## 7. Defect severity and register

| Severity | Definition |
|---|---|
| Sev-1 | Wrong or lost financial data, a cross-user data leak, a security or isolation failure, a crash on launch or on a core journey, any contact with production |
| Sev-2 | A journey cannot be completed, a wrong money figure is displayed, a blocking accessibility failure (control without name or role on a P0 screen), repeated duplicate submission |
| Sev-3 | Journey completes with a workaround; wrong copy that does not misstate money; layout defect that hides no control |
| Sev-4 | Cosmetic |

`defects.md` has one table: `Defect ID | Severity | Status | Row IDs | Summary | Evidence | Owner`. Status is `open`, `fixed` or
`wontfix` (owner decision). A `PASS` row may reference only Sev-3 or Sev-4 defects, or ones that are not open. BR-5 requires zero open Sev-1 and Sev-2 defects.

## 8. Owner sign-off

`signoff.md` states the run ID, the app and backend commit SHAs, the counts of `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`,
`WAIVED` rows, the open defect counts by severity, any waiver IDs, and the owner's name and date. Only the owner signs.
A run with any `NOT RUN` or `BLOCKED` row is not complete for BR-5.

## 9. Validator

```bash
node tools/qa/validate-qa-evidence.mjs            # whole repository check
node --test tools/qa/validate-qa-evidence.test.mjs   # the validator's own tests
```

Checks: exactly J01–J20 once per platform and 40 rows in the template; every mandatory field present and none
duplicated or renamed; no `PASS` or `FAIL` without the required evidence; `WAIVED` only for J18 with a signed register entry;
no stale OS floor outside a recorded exception; no production endpoint, token or credential pattern in QA files;
run records carry a staging isolation line; every `PASS` or `FAIL` row names the **same** staging identifier as its run record,
and that identifier is an `ACTIVE` register entry named by the run's isolation line; no run is `VERIFIED` while the denylist
has no owner-approved entry; a `WAIVED` row is accepted only on a platform its signed waiver lists. The validator checks
**structure and consistency**. It cannot prove that a test was really run, that an owner really signed, or that a
screenshot is genuine; review of the run by the owner remains required.

The validator is not wired into CI by this task (that is a pipeline change for the owner to approve).
