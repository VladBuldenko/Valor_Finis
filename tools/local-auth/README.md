# Local Supabase Auth for mobile QA (LOCAL-AUTH-001)

Runs the **real** Supabase Auth (GoTrue) locally so the real app and the real FastAPI can be tested end to end
without any hosted service. Local only: never run `supabase link`, `db push`, `db pull` or `functions deploy`.
Evidence from the first run: [../../docs/mvp/local-preflight-mobile-acceptance-001.md](../../docs/mvp/local-preflight-mobile-acceptance-001.md).

Why this is needed: the app always sends `Authorization: Bearer <Supabase token>`, and FastAPI validates that token by
calling `${SUPABASE_URL}/auth/v1/user` even when `AUTH_MODE=development`. `X-User-Id` is only a fallback when no
bearer header is sent, so it cannot serve the app.

## Prerequisites
Docker (>= 7 GB RAM for the full stack; this minimal stack needs far less), Node 22, Postgres.app or another
**disposable** local Postgres listening on port 54332 for the application database, Tesseract (`brew install tesseract`),
and the API virtualenv at `services/api/.venv` (it provides SQLAlchemy, which `api-env.sh` uses to validate the database URL;
set `LOCAL_AUTH_PYTHON` to another interpreter that has SQLAlchemy if you keep the venv elsewhere).
Nothing is installed globally: the Supabase CLI runs through `npx supabase@3.1.0`.

## How to read the commands
Every block says where it runs. Each terminal first needs the repository root, from any directory inside the repo:
```bash
export VF_ROOT="$(git rev-parse --show-toplevel)"
```
Blocks that change directory either do it in a `( ... )` subshell, so your shell stays where it was, or chain with `&&`,
so nothing after a failed `cd` or a failed validation runs. Never replace `&&` with a newline or `;`.

## 1. Start the local Auth stack (any directory)
```bash
( cd "$VF_ROOT/tools/local-auth" && DO_NOT_TRACK=1 npx supabase@3.1.0 start -x realtime,storage-api,imgproxy,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor )
```
```bash
( cd "$VF_ROOT/tools/local-auth" && umask 077 && npx supabase@3.1.0 status -o env > status.env )
```
`status.env` is gitignored, mode 600 and holds local keys. `api-env.sh` reads only its public `API_URL` and
`PUBLISHABLE_KEY`; the secret and service-role keys never enter your shell. Kept services: Auth (`:54321/auth/v1`),
the Kong gateway, the Auth Postgres (`:54322`) and Mailpit (UI `:54324`). `supabase/config.toml` turns email
confirmation on and allows the redirect `valorfinis://auth/callback`.

## 2. Create the disposable application database (any directory)
```bash
createdb -h 127.0.0.1 -p 54332 -U postgres valor_localauth
```
Only this exact database is accepted by the tooling. Never run pytest against it (pytest needs a `*_test` database).

## 3. Migrate and run the API (terminal 1; one command, run from any directory)
```bash
export LOCAL_AUTH_APP_DATABASE_URL=postgresql://postgres@127.0.0.1:54332/valor_localauth
```
```bash
cd "$VF_ROOT/tools/local-auth" && source ./api-env.sh && cd ../../services/api && .venv/bin/python -m alembic upgrade head && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```
`api-env.sh` must be **sourced** from `tools/local-auth`. It validates everything first and exports nothing unless all checks
pass: the database URL must be exactly `postgresql://[user@]127.0.0.1|localhost|[::1]:54332/valor_localauth` with no query
parameters (no `?host=` overrides), `API_URL` must be a plain loopback URL, and no libpq variable (`PGHOST`, `PGHOSTADDR`,
`PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`, `PGSYSCONFDIR`, `PGOPTIONS`) may be set. On rejection it prints a
fixed reason, returns non-zero, and the `&&` chain stops before Alembic and uvicorn. The only key the API receives is the
public publishable key. If your shell already exports `SECRET_KEY`, `SERVICE_ROLE_KEY`, `JWT_SECRET` or `ANON_KEY` for
other reasons, start the API with `env -u SECRET_KEY -u SERVICE_ROLE_KEY -u JWT_SECRET -u ANON_KEY` before `.venv/bin/python`.

## 4. Mobile (terminal 2)
`apps/mobile/.env.local` (gitignored) must hold only: `EXPO_PUBLIC_API_URL=http://127.0.0.1:8766`,
`EXPO_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<PUBLISHABLE_KEY from status.env>`.
Never put the secret or service-role key in an `EXPO_PUBLIC_*` variable.
```bash
cd "$VF_ROOT/apps/mobile" && REACT_NATIVE_PACKAGER_HOSTNAME=127.0.0.1 CI=1 npx expo start --port 8081
```
Do **not** use `--localhost` (it binds `[::1]` only). Then, from any directory:
```bash
xcrun simctl openurl booted "exp://127.0.0.1:8081"
```
A physical phone cannot use `127.0.0.1`: use the Mac's LAN address for all three URLs.

## Signup / email confirmation in Expo Go
Expo Go cannot open the `valorfinis://` scheme. Open the confirmation mail in Mailpit (`http://127.0.0.1:54324`),
request the link without following the redirect (`curl -s -o /dev/null -w '%{redirect_url}' '<link>'`), take the
`code=` value and deliver it to the app: `xcrun simctl openurl booted "exp://127.0.0.1:8081/--/auth/callback?code=<code>"`.
Do not paste the code into logs or commits.

## Stop (keeps your data) and restart
Stop Metro and uvicorn with Ctrl+C in their terminals, then, from any directory:
```bash
( cd "$VF_ROOT/tools/local-auth" && npx supabase@3.1.0 stop )
```
This stops only this project's containers; the Auth data volumes are **kept**. To restart, run step 1's `start` command
again (and step 3 for the API). Restarting restores the previous Auth users. `status.env` can be reused (the local keys do
not change); recreate it with the second command of step 1 if it is missing.

## Reset (only when you explicitly want to discard all local users and data)
```bash
( cd "$VF_ROOT/tools/local-auth" && npx supabase@3.1.0 stop --no-backup && dropdb -h 127.0.0.1 -p 54332 -U postgres valor_localauth && rm -rf ./status.env ./receipt-uploads )
```
This **deletes** the local Auth data and the `valor_localauth` database. It never touches other Docker containers or
databases: the CLI acts only on the project id `valor-local-auth` from `supabase/config.toml`, and every path is relative to
`tools/local-auth`.

## Tests for this tooling (offline)
No Docker, network, real database or real credentials; runs every case in bash and zsh with fake values:
```bash
LOCAL_AUTH_PYTHON="$VF_ROOT/services/api/.venv/bin/python" bash "$VF_ROOT/tools/local-auth/tests/test-api-env.sh"
```
