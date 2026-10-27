#!/usr/bin/env bash
# Fail-closed production migration runner (VF-020E10 OPS-02 corrections).
#
# Usage:   run_guarded_migration.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name>
#
# Run it ONLY for a migration gate the owner authorized in writing, naming that exact revision.
# It applies EXACTLY the named revision (never `head`) and refuses to call `alembic upgrade`
# unless EVERY prerequisite below succeeded. There is no override flag.
#
#   1. input and environment validation (libpq PG* variables for the checks, DATABASE_URL for
#      Alembic; PGSERVICE / PGSERVICEFILE / PGHOSTADDR refused);
#   2. endpoint proof: the PG* path and the DATABASE_URL path must reach the SAME database
#      server (same database oid, same postmaster start time, same database name = the expected
#      one, same role) and BOTH must honour lock_timeout = 5s;
#   3. `alembic current` must report exactly the parent revision;
#   4. the read-only preflight of the target must PASS;
#   5. only then: `alembic upgrade <revision>` under lock_timeout 5s / statement_timeout 60s;
#   6. the read-only post-check(s) must PASS.
#
# Exit status: 0 = migrated and verified; 11 = STOPPED BEFORE any migration (nothing changed);
# 12 = `alembic upgrade` itself failed (single transaction: nothing committed, verify with the
# preflight); 13 = migrated, but a post-check did not PASS (report; do not retry);
# 64 = refused to start (usage or unsafe environment).
#
# Credentials come only from the environment (never arguments); nothing here prints a URL.
# MIGRATION_PYTHON (the interpreter used for the proof and for Alembic) exists for the disposable-database
# tests only; production use leaves it unset.
set -u
set -o pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$DIR/../../../services/api" && pwd)"
PY="${MIGRATION_PYTHON:-$API_DIR/.venv/bin/python}"

refuse() { echo "REFUSED: $1" >&2; exit 64; }
stop() { echo "STOP (before any migration): $1" >&2; exit 11; }

[ "$#" -eq 2 ] || refuse "usage: run_guarded_migration.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name>"
TARGET="$1"
EXPECTED_DB="$2"

case "$TARGET" in
    a7c3e91d5b24) PARENT="e0503e9ca9d3"; PREFLIGHT="e9a_preflight"; POSTCHECKS="e9a_postcheck" ;;
    c4d8a2f6e193) PARENT="a7c3e91d5b24"; PREFLIGHT="e10_preflight"; POSTCHECKS="e10_postcheck e9a_postcheck" ;;
    *) refuse "only revisions a7c3e91d5b24 and c4d8a2f6e193 may be applied with this runner" ;;
esac

[[ "$EXPECTED_DB" =~ ^[A-Za-z0-9_]+$ ]] || refuse "expected database name must match [A-Za-z0-9_]+"
[ -n "${PGHOST:-}" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGDATABASE:-}" ] || refuse "PGHOST, PGUSER and PGDATABASE must be set"
[ "$PGDATABASE" = "$EXPECTED_DB" ] || refuse "PGDATABASE does not equal the expected database name"
[ -n "${DATABASE_URL:-}" ] || refuse "DATABASE_URL must be set (Alembic uses it)"
for forbidden in PGSERVICE PGSERVICEFILE PGHOSTADDR; do
    [ -z "${!forbidden:-}" ] || refuse "unset $forbidden: it can override the validated connection settings"
done
[ -x "$PY" ] || refuse "python interpreter not found: set MIGRATION_PYTHON"
command -v psql >/dev/null 2>&1 || refuse "psql is required"

# TLS for BOTH connection paths (libpq's PGSSLMODE also governs the Alembic connection when the URL
# names no sslmode). A plain connection is accepted only to localhost, for the disposable test databases.
case "${PGSSLMODE:-require}" in
    require|verify-ca|verify-full) ;;
    *)
        if [ "${ALLOW_INSECURE_LOCAL_TEST:-}" = "1" ] && { [ "$PGHOST" = "localhost" ] || [ "$PGHOST" = "127.0.0.1" ]; }; then
            :
        else
            refuse "PGSSLMODE must be require, verify-ca or verify-full"
        fi
        ;;
esac
export PGSSLMODE="${PGSSLMODE:-require}"

export PGCONNECT_TIMEOUT=10
export PGAPPNAME="vf-guarded-migration-$TARGET"
export PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=60000"

# --- 2. endpoint proof -------------------------------------------------------------------------
FP_SQL="SELECT (SELECT oid FROM pg_database WHERE datname = current_database()), extract(epoch FROM pg_postmaster_start_time())::bigint, current_database(), current_user, current_setting('lock_timeout')"

VIA_PG="$(psql -X -q -At -v ON_ERROR_STOP=1 -c "$FP_SQL" </dev/null 2>/dev/null)" || stop "cannot query the server through the PG* variables"
VIA_URL="$(cd "$API_DIR" && "$PY" - "$FP_SQL" <<'PY' 2>/dev/null
import os, sys
from sqlalchemy import create_engine, text
with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
    print("|".join(str(value) for value in connection.execute(text(sys.argv[1])).one()))
PY
)" || stop "cannot query the server through DATABASE_URL"

[ -n "$VIA_PG" ] && [ "$VIA_PG" = "$VIA_URL" ] || stop "the PG* variables and DATABASE_URL do not reach the same server and database"
IFS='|' read -r _oid _start FP_DB _role FP_LOCK <<<"$VIA_URL"
[ "$FP_DB" = "$EXPECTED_DB" ] || stop "connected database is not the expected one"
[ "$FP_LOCK" = "5s" ] || stop "lock_timeout is not 5s on this endpoint (a pooler may have dropped the startup options)"

# --- 3. current revision -----------------------------------------------------------------------
CURRENT="$(cd "$API_DIR" && "$PY" -m alembic current 2>/dev/null)" || stop "alembic current failed"
CURRENT_REVISIONS="$(printf '%s\n' "$CURRENT" | grep -Eo '^[0-9a-f]{12}' || true)"
[ "$CURRENT_REVISIONS" = "$PARENT" ] || stop "alembic current is not exactly the parent revision $PARENT"

# --- 4. read-only preflight (the runner refuses DATABASE_URL, so it is removed for the checks only) ---
env -u DATABASE_URL "$DIR/run_readonly_check.sh" "$PREFLIGHT" "$EXPECTED_DB" || stop "the $PREFLIGHT did not PASS"

# --- 5. the exact upgrade ----------------------------------------------------------------------
echo "applying exactly $TARGET"
ERR_FILE="$(mktemp)" || stop "cannot create a private temporary file"
trap 'rm -f "$ERR_FILE"' EXIT
( cd "$API_DIR" && "$PY" -m alembic upgrade "$TARGET" ) >/dev/null 2>"$ERR_FILE"
UPGRADE_STATUS=$?
if [ "$UPGRADE_STATUS" -ne 0 ]; then
    # first line only, quoted strings removed (they can name hosts, roles or databases)
    head -n 1 "$ERR_FILE" | sed -E -e 's/"[^"]*"/"<redacted>"/g' -e "s/'[^']*'/'<redacted>'/g" | cut -c1-200 >&2
    echo "alembic upgrade failed (exit $UPGRADE_STATUS); one transaction: nothing was committed. Verify with the preflight." >&2
    exit 12
fi

# --- 6. post-checks ----------------------------------------------------------------------------
for CHECK in $POSTCHECKS; do
    if ! env -u DATABASE_URL "$DIR/run_readonly_check.sh" "$CHECK" "$EXPECTED_DB"; then
        echo "MIGRATED to $TARGET, but $CHECK did not PASS: report, do not retry." >&2
        exit 13
    fi
done

echo "RESULT: MIGRATED AND VERIFIED ($TARGET)"
exit 0
