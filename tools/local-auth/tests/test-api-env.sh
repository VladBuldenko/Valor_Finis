#!/usr/bin/env bash
# Offline regression tests for tools/local-auth/api-env.sh (+ check_database_url.py), run in bash AND zsh.
# Fake URLs and fake credentials only: no Docker, network, real database or real key. The validator only parses.
#   LOCAL_AUTH_PYTHON=<python with SQLAlchemy> bash tools/local-auth/tests/test-api-env.sh
set -u
LA="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBIN="${LOCAL_AUTH_PYTHON:-$LA/../../services/api/.venv/bin/python}"
{ [ -x "$PYBIN" ] && "$PYBIN" -c 'import sqlalchemy'; } 2>/dev/null || { echo "need a Python with SQLAlchemy: set LOCAL_AUTH_PYTHON" >&2; exit 2; }
T="$(mktemp -d)"; trap 'rm -rf -- "${T:?}"' EXIT

OKURL='postgresql://postgres@127.0.0.1:54332/valor_localauth'
SECRETS='FAKE-SECRET-KEY-1 FAKE-SERVICE-ROLE-2 FAKE-JWT-SECRET-3 FAKE-ANON-4 FAKE-ADMIN-DB-PW-5 FAKE-URL-PW-6'
PRIV='SECRET_KEY|SERVICE_ROLE_KEY|JWT_SECRET|ANON_KEY|DB_URL|API_URL|PUBLISHABLE_KEY'
PASS=0; FAIL=0
bad() { FAIL=$((FAIL + 1)); echo "FAIL [$SH] $1" >&2; }
ok() { PASS=$((PASS + 1)); }
check() { if eval "$2"; then ok; else bad "$1"; fi; }

# The code each shell runs: source the script from its own directory and record what the caller's shell looks like.
CHILD='
cd "$1" || exit 99
[ "$2" = "-" ] || export LOCAL_AUTH_APP_DATABASE_URL="$2"
eval "$3"
before=$-
source ./api-env.sh > out.txt 2>&1
{ echo "rc=$?"
  [ "$before" = "$-" ] && echo opts=same || echo opts=changed
  [ -n "${_la_here+x}" ] && echo var=leaked
  type _la_setup > /dev/null 2>&1 && echo func=leaked
} > res.txt
env > env.txt
'

# run <name> <database-url or -> [status: ok|missing|noapi|badapi|nopub] [shell snippet run first]
run() {
  C="$T/$SH-$1"; mkdir -p "$C"; cp "$LA/api-env.sh" "$LA/check_database_url.py" "$C/"
  api='http://127.0.0.1:54321'; [ "${3:-ok}" = badapi ] && api='https://abc.supabase.co'
  case "${3:-ok}" in
    missing) ;;
    nopub) printf 'API_URL="%s"\nSECRET_KEY="FAKE-SECRET-KEY-1"\n' "$api" > "$C/status.env" ;;
    noapi) printf 'PUBLISHABLE_KEY="fake-publishable"\n' > "$C/status.env" ;;
    *) printf 'API_URL="%s"\nPUBLISHABLE_KEY="fake-publishable"\nSECRET_KEY="FAKE-SECRET-KEY-1"\nSERVICE_ROLE_KEY="FAKE-SERVICE-ROLE-2"\nJWT_SECRET="FAKE-JWT-SECRET-3"\nANON_KEY="FAKE-ANON-4"\nDB_URL="postgresql://postgres:FAKE-ADMIN-DB-PW-5@127.0.0.1:54322/postgres"\n' "$api" > "$C/status.env" ;;
  esac
  ( cd "$C" && env -i PATH="$PATH" HOME="$HOME" LOCAL_AUTH_PYTHON="$PYBIN" KEEP_ME=keep "$SH" -c "$CHILD" child "$C" "$2" "${4:-:}" )
}

# A rejected run must fail, export nothing, leak no secret, and leave the caller's shell untouched.
reject() { # <name> <db-url> [status] [snippet]
  run "$@"
  check "$1: rejected (rc != 0)" "! grep -qx 'rc=0' '$C/res.txt'"
  check "$1: nothing exported (DATABASE_URL/AUTH_MODE/SUPABASE_*)" "! grep -qE '^(DATABASE_URL|AUTH_MODE|SUPABASE_URL|SUPABASE_PUBLISHABLE_KEY)=' '$C/env.txt'"
  check "$1: no privileged variable in the environment" "! grep -qE '^($PRIV)=' '$C/env.txt'"
  # the caller's own input variable is excluded: it legitimately holds the fake URL (and its fake password)
  check "$1: no secret value in output or environment" "! { cat '$C/out.txt'; grep -v '^LOCAL_AUTH_APP_DATABASE_URL=' '$C/env.txt'; } | grep -qF -e ${SECRETS// / -e }"
  check "$1: shell options and helpers restored" "grep -qx opts=same '$C/res.txt' && ! grep -qE '^(var|func)=leaked' '$C/res.txt'"
  check "$1: unrelated variable preserved" "grep -qx KEEP_ME=keep '$C/env.txt'"
}

for SH in bash zsh; do
  command -v "$SH" > /dev/null || { echo "skip: $SH not installed"; continue; }

  # 1/14 valid URL and successful setup; 13 no privileged credential exported after success
  run valid "$OKURL"
  check "valid: accepted" "grep -qx 'rc=0' '$C/res.txt'"
  check "valid: DATABASE_URL, AUTH_MODE, SUPABASE_URL set" "grep -qx 'DATABASE_URL=$OKURL' '$C/env.txt' && grep -qx AUTH_MODE=supabase '$C/env.txt' && grep -qx SUPABASE_URL=http://127.0.0.1:54321 '$C/env.txt'"
  check "valid: only the publishable key is given to the API" "grep -qx SUPABASE_PUBLISHABLE_KEY=fake-publishable '$C/env.txt' && ! grep -qE '^($PRIV)=' '$C/env.txt' && ! grep -qF -e ${SECRETS// / -e } '$C/env.txt' '$C/out.txt'"
  check "valid: receipt dir created inside the tool dir" "[ -d '$C/receipt-uploads' ] && grep -qx RECEIPT_UPLOAD_DIR='$C/receipt-uploads' '$C/env.txt'"
  check "valid: shell options, helpers and unrelated variable preserved" "grep -qx opts=same '$C/res.txt' && ! grep -qE '^(var|func)=leaked' '$C/res.txt' && grep -qx KEEP_ME=keep '$C/env.txt'"
  run keep-caller-secrets "$OKURL" ok 'export SECRET_KEY=caller-own-value'
  check "valid: a variable the caller already had is not touched" "grep -qx SECRET_KEY=caller-own-value '$C/env.txt'"

  # 2 remote host, 3 lookalikes, 4 query-host override, 5 multiple hosts / socket / hostaddr, 6 db name, 7 port, 8 malformed
  reject remote-host 'postgresql://postgres@db.example.com:54332/valor_localauth'
  reject hosted-supabase 'postgresql://postgres:FAKE-URL-PW-6@db.abc.supabase.co:54332/valor_localauth'
  reject lookalike-suffix 'postgresql://postgres@127.0.0.1.evil.example:54332/valor_localauth'
  reject lookalike-prefix 'postgresql://postgres@localhost.evil.example:54332/valor_localauth'
  reject userinfo-trick 'postgresql://127.0.0.1@evil.example:54332/valor_localauth'
  reject query-host "$OKURL?host=evil.example"
  reject query-host-with-password 'postgresql://postgres:FAKE-URL-PW-6@127.0.0.1:54332/valor_localauth?host=evil.example'
  reject query-hostaddr "$OKURL?hostaddr=203.0.113.9"
  reject query-socket "$OKURL?host=/tmp"
  reject multi-host-query "$OKURL?host=127.0.0.1&host=evil.example"
  reject multi-host-authority 'postgresql://postgres@127.0.0.1:54332,evil.example:5432/valor_localauth'
  reject unix-socket-url 'postgresql://postgres@/valor_localauth'
  reject wrong-database 'postgresql://postgres@127.0.0.1:54332/postgres'
  reject wrong-database-suffix 'postgresql://postgres@127.0.0.1:54332/valor_localauth_test'
  reject wrong-port 'postgresql://postgres@127.0.0.1:5432/valor_localauth'
  reject missing-port 'postgresql://postgres@127.0.0.1/valor_localauth'
  reject wrong-driver 'mysql://postgres@127.0.0.1:54332/valor_localauth'
  reject malformed 'not a url'
  reject malformed-fragment "$OKURL#x"
  reject malformed-space " $OKURL"

  # 9 non-loopback API_URL, 10 missing status.env, 11 missing required configuration, 12 failures leak nothing (in reject)
  reject api-url-not-loopback "$OKURL" badapi
  reject status-env-missing "$OKURL" missing
  reject status-env-no-api-url "$OKURL" noapi
  reject status-env-no-publishable-key "$OKURL" nopub
  reject database-url-unset -
  reject libpq-hostaddr "$OKURL" ok 'export PGHOSTADDR=203.0.113.9'
  reject libpq-host "$OKURL" ok 'export PGHOST=evil.example'
  reject python-missing "$OKURL" ok 'export LOCAL_AUTH_PYTHON=/nonexistent/python'
done

echo "api-env tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
