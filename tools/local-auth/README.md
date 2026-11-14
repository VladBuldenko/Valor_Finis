# Local Supabase Auth for mobile QA (LOCAL-AUTH-001)

Runs the **real** Supabase Auth (GoTrue) locally so the real app and the real FastAPI can be tested end to end
without any hosted service. Local only: never run `supabase link`, `db push`, `db pull` or `functions deploy`.
Evidence from the first run: [../../docs/mvp/local-preflight-mobile-acceptance-001.md](../../docs/mvp/local-preflight-mobile-acceptance-001.md).

Why this is needed: the app always sends `Authorization: Bearer <Supabase token>`, and FastAPI validates that token by
calling `${SUPABASE_URL}/auth/v1/user` even when `AUTH_MODE=development`. `X-User-Id` is only a fallback when no
bearer header is sent, so it cannot serve the app.

## Prerequisites
Docker (>= 7 GB RAM for the full stack; this minimal stack needs far less), Node 22, Postgres.app or another
**disposable** local Postgres for the application database, Tesseract (`brew install tesseract`).
Nothing is installed globally: the Supabase CLI runs through `npx supabase@3.1.0`.

## Start (from this directory)
```bash
cd tools/local-auth
export DO_NOT_TRACK=1
npx supabase@3.1.0 start -x realtime,storage-api,imgproxy,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
( umask 077; npx supabase@3.1.0 status -o env > status.env )     # gitignored, mode 600; holds local keys
```
Kept services: Auth (`:54321/auth/v1`), the Kong gateway, the Auth Postgres (`:54322`) and Mailpit (UI `:54324`).
`supabase/config.toml` turns email confirmation on and allows the redirect `valorfinis://auth/callback`.

## Application database and API
```bash
createdb -h 127.0.0.1 -p 54332 -U postgres valor_localauth          # DISPOSABLE database only
export LOCAL_AUTH_APP_DATABASE_URL=postgresql://postgres@127.0.0.1:54332/valor_localauth
source tools/local-auth/api-env.sh
cd services/api && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```
Never run pytest against this database (pytest needs a `*_test` database).

## Mobile
`apps/mobile/.env.local` (gitignored) must hold only: `EXPO_PUBLIC_API_URL=http://127.0.0.1:8766`,
`EXPO_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<PUBLISHABLE_KEY from status.env>`.
Never put the secret or service-role key in an `EXPO_PUBLIC_*` variable.
```bash
cd apps/mobile
REACT_NATIVE_PACKAGER_HOSTNAME=127.0.0.1 CI=1 npx expo start --port 8081      # do NOT use --localhost (binds [::1] only)
xcrun simctl openurl booted "exp://127.0.0.1:8081"
```
A physical phone cannot use `127.0.0.1`: use the Mac's LAN address for all three URLs.

## Signup / email confirmation in Expo Go
Expo Go cannot open the `valorfinis://` scheme. Open the confirmation mail in Mailpit (`http://127.0.0.1:54324`),
request the link without following the redirect (`curl -s -o /dev/null -w '%{redirect_url}' '<link>'`), take the
`code=` value and deliver it to the app: `xcrun simctl openurl booted "exp://127.0.0.1:8081/--/auth/callback?code=<code>"`.
Do not paste the code into logs or commits.

## Stop (keeps your data) and restart
```bash
cd tools/local-auth && npx supabase@3.1.0 stop      # stops only this project's containers; Auth data volumes are KEPT
npx supabase@3.1.0 start -x realtime,storage-api,imgproxy,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
```
Restarting restores the previous Auth users. `status.env` can be reused (the local keys do not change); regenerate it
with the `status -o env` command above if it is missing. Stop Metro and uvicorn with Ctrl+C in their terminals.

## Reset (only when you explicitly want to discard all local users and data)
Run from anywhere inside the repository; every path is scoped to `tools/local-auth` and the disposable database:
```bash
cd "$(git rev-parse --show-toplevel)/tools/local-auth"
npx supabase@3.1.0 stop --no-backup          # DELETES this project's local Auth data volumes
dropdb -h 127.0.0.1 -p 54332 -U postgres valor_localauth
rm -rf ./status.env ./receipt-uploads
```
These commands never touch other Docker containers or databases: the CLI acts only on the project id
`valor-local-auth` from `supabase/config.toml`.
