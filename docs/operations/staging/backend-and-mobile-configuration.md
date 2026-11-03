# Backend and Mobile Staging Configuration (VF-QA-1)

Variable **names** only. Values live in the staging secret store and the operator-held approved-targets file; no production value
may appear in any staging shell, container, build or document. Nothing here has been deployed or built.

## 1. Backend (staging instance or local container)

The application has **no environment-name variable** (`app/core/app_config.py` reads none), so the environment is defined by the
values it is given, never by a name. That is why the guard checks the database and the Supabase project themselves.

| Variable | Staging value | Notes |
|---|---|---|
| `AUTH_MODE` | `supabase` | Never `development` on staging: `development` trusts an `X-User-Id` header with no signature check. The guard refuses any other value |
| `DATABASE_URL` | staging database, `postgresql://<user>:<password>@<host>:<port>/<name>_staging?sslmode=require` | Direct or session-mode endpoint (not port 6543). From the secret store; never in a file in the repository |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` of the **staging** project | Must equal the approved project reference |
| `SUPABASE_PUBLISHABLE_KEY` | staging key | Used to validate sessions against `/auth/v1/user` |
| `SUPABASE_SECRET_KEY` | staging key | Only when `RECEIPT_STORAGE_DRIVER=supabase`; backend only, never in a client or log |
| `RECEIPT_STORAGE_DRIVER` | `supabase` (staging bucket) or `local` (a local container) | |
| `RECEIPT_STORAGE_BUCKET` | a bucket in the staging project | Never a bucket of the production project |
| `RECEIPT_OCR_DRIVER` | `tesseract` or `unconfigured` | |
| `RULE_EVENT_BACKGROUND_DISPATCH` | `true` (default) | The three exactly-once triggers of BR-12 need it on for the post-Income drain |
| `PORT` | as the host requires | |

Local container option: build `services/api/Dockerfile` and pass the variables from an env file kept **outside** the repository.
`docker-compose.yml` describes the local development stack and must not be pointed at staging credentials.

Dispatcher rehearsal (OPS03 row 11): `python -m app.modules.financial_rules.dispatcher` runs against the **staging** database only, in
a shell where `staging_ops identify` has just passed with the same environment.

## 2. Operator shell for `staging_ops`

The shell holds `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `AUTH_MODE=supabase` and **no** `PG*` variable. The tool
refuses `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`, `PGOPTIONS`, `PGSSLMODE`, `PGTARGETSESSIONATTRS`
and `PGSYSCONFDIR`. The existing read-only OPS checks (`docs/operations/sql/run_readonly_check.sh`) are the opposite: they require
`PG*` variables, so run them in a **separate** shell prepared for that script, with the same target.

## 3. Mobile QA build

| Variable | Staging value |
|---|---|
| `EXPO_PUBLIC_API_URL` | the staging API origin (https) |
| `EXPO_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` of the staging project |
| `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the staging publishable key |

These are inlined into the JavaScript bundle at build or bundle time (`apps/mobile/src/config/env.ts`), so what a build targets is
decided when it is made. Verification, by the person who builds, with **the same environment** as the build:

```bash
node tools/qa/staging-fingerprint.mjs --register docs/mvp/qa-evidence/staging-register.md --staging STG-1
```

It prints origin fingerprints (never a URL or key), refuses an `http` origin and any production-denylist match, and exits non-zero
on any mismatch. Save the output as `artifacts/staging-fingerprint.txt` of the run and link it from the run record
([QA-0 evidence and isolation, section 3.2](../../mvp/qa-evidence-and-staging-isolation.md)). Prerequisite: the owner has filled the
QA-0 register (an `ACTIVE` staging entry and at least one owner-recorded production fingerprint); until then every run stays
`NOT VERIFIED`.

`GET /health` proves nothing about the environment: it returns the same body everywhere. The mobile database guard and the
fingerprint helper are different checks: the helper proves what a **build** points at, `staging_ops` proves what a **database
operation** will change. Neither replaces the other.

The app-unique URL scheme is not set by QA-1 (`apps/mobile/app.json` keeps the generic scheme until MF-4).
