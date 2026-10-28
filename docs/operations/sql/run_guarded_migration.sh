#!/usr/bin/env bash
# Fail-closed production migration runner (VF-020E10 OPS-02 corrections).
#
# Usage:   BACKUP_EVIDENCE_FILE=<receipt> run_guarded_migration.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name>
#
# This runner moves ONE existing database between two exact revisions. It is never a bootstrap: an empty or
# unmigrated database (no `alembic current`) is refused. Building a new staging database is a separate,
# staging-only procedure (docs/mvp/mvp-ops03-and-staging-prerequisites.md section 2.5).
#
# Run it ONLY for a migration gate the owner authorized in writing, naming that exact revision.
# It applies EXACTLY the named revision (never `head`) and refuses to call `alembic upgrade`
# unless EVERY prerequisite below succeeded. There is no override flag.
#
#   1. input and environment validation (libpq PG* variables for the checks, DATABASE_URL for
#      Alembic; PGSERVICE / PGSERVICEFILE / PGHOSTADDR refused);
#   1b. backup evidence: BACKUP_EVIDENCE_FILE must be a receipt SEALED by verify_backup_restore.sh (which performed a real
#      restore and the read-only preflight on a disposable database), bound to THIS target, database and source
#      revision; backup_evidence.py re-inspects the dump (archive database name, alembic_version data, required tables,
#      SHA-256, age < 24 h, server major equals the live server's);
#   2. endpoint proof: the PG* path and the DATABASE_URL path must reach the SAME database
#      server (same database oid, same postmaster start time, same database name = the expected
#      one, same role) and BOTH must honour lock_timeout = 5s and statement_timeout = 1min;
#   3. `alembic current` must report exactly the parent revision;
#   4. the read-only preflight of the target must PASS;
#   2b. a session-level advisory lock (never waited for) serializes concurrent runs; held until this process exits;
#   4b. immediately before the upgrade the endpoint proof is repeated and must be identical to the first one
#      (same server instance), and `alembic current` is read again (narrows the time-of-check window);
#   5. only then: `alembic upgrade <revision>` under lock_timeout 5s / statement_timeout 60s;
#   6. the read-only post-check(s) must PASS.
#
# Exit status: 0 = migrated and verified; 11 = STOPPED BEFORE any migration (nothing changed);
# 12 = `alembic upgrade` itself failed (single transaction: nothing committed, verify with the
# preflight); 13 = migrated, but a post-check did not PASS (report; do not retry);
# 64 = refused to start (usage or unsafe environment).
#
# Credentials come only from the environment (never arguments); nothing here prints a URL.
# MIGRATION_PYTHON (the interpreter used for the proof and for Alembic) exists for the disposable-database tests only
# and is refused unless the whole local test mode holds (flag, local hosts, a *_test database); production leaves it unset.
set -u
set -o pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$DIR/../../../services/api" && pwd)"
PY="${MIGRATION_PYTHON:-$API_DIR/.venv/bin/python}"

LOCK_PID=""; ERR_FILE=""; LOCK_STATUS=""
cleanup() {
    # Stopping the holder closes its connection, which releases the advisory lock; wait so the lock is gone at exit.
    [ -z "$LOCK_PID" ] || { kill "$LOCK_PID" >/dev/null 2>&1; wait "$LOCK_PID" >/dev/null 2>&1; }
    [ -z "$ERR_FILE" ] || rm -f "$ERR_FILE"
    [ -z "$LOCK_STATUS" ] || rm -f "$LOCK_STATUS" "$LOCK_STATUS.tmp"
}
trap cleanup EXIT

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
# Disposable local test mode (it relaxes TLS and allows the MIGRATION_PYTHON test double). EVERY condition must hold:
# the explicit flag, a local PG* host, a local DATABASE_URL host, and an expected database whose name ends in `_test`.
# Merely being on localhost is never enough (SR-03).
LOCAL_TEST_MODE=no
URL_HOST="${DATABASE_URL#*://}"; URL_HOST="${URL_HOST#*@}"; URL_HOST="${URL_HOST%%[/?:]*}"
if [ "${ALLOW_INSECURE_LOCAL_TEST:-}" = "1" ] \
   && { [ "$PGHOST" = "localhost" ] || [ "$PGHOST" = "127.0.0.1" ]; } \
   && { [ "$URL_HOST" = "localhost" ] || [ "$URL_HOST" = "127.0.0.1" ]; } \
   && [[ "$EXPECTED_DB" =~ ^[A-Za-z0-9_]*_test$ ]]; then
    LOCAL_TEST_MODE=yes
    echo "WARNING: disposable local TEST MODE (relaxed TLS, interpreter override allowed). Never use for a real database." >&2
fi
[ -z "${MIGRATION_PYTHON:-}" ] || [ "$LOCAL_TEST_MODE" = "yes" ] || refuse "MIGRATION_PYTHON is only accepted in the disposable local test mode (local hosts and a *_test database)"
case "$DATABASE_URL" in
    *[Ss][Ss][Ll][Mm][Oo][Dd][Ee]=disable*|*[Ss][Ss][Ll][Mm][Oo][Dd][Ee]=allow*|*[Ss][Ss][Ll][Mm][Oo][Dd][Ee]=prefer*)
        [ "$LOCAL_TEST_MODE" = "yes" ] || refuse "DATABASE_URL must not weaken TLS (sslmode disable, allow or prefer)" ;;
esac
[ -x "$PY" ] || refuse "python interpreter not found (expected $API_DIR/.venv/bin/python)"
command -v psql >/dev/null 2>&1 || refuse "psql is required"
command -v pg_restore >/dev/null 2>&1 || refuse "pg_restore is required (it verifies the backup file)"
[ -n "${BACKUP_EVIDENCE_FILE:-}" ] || refuse "BACKUP_EVIDENCE_FILE must name the backup and restore-verification receipt"

# TLS for BOTH connection paths (libpq's PGSSLMODE also governs the Alembic connection when the URL
# names no sslmode). A plain connection is accepted only to localhost, for the disposable test databases.
case "${PGSSLMODE:-require}" in
    require|verify-ca|verify-full) ;;
    *)
        [ "$LOCAL_TEST_MODE" = "yes" ] || refuse "PGSSLMODE must be require, verify-ca or verify-full (relaxed TLS only in the disposable local test mode)"
        ;;
esac
export PGSSLMODE="${PGSSLMODE:-require}"

export PGCONNECT_TIMEOUT=10
export PGAPPNAME="vf-guarded-migration-$TARGET"
export PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=60000"

# --- 1b. backup evidence (local files only; no database is contacted) --------------------------
# The receipt must have been produced by verify_backup_restore.sh (sealed, performed restore + preflight on a
# disposable database) and backup_evidence.py re-inspects the dump itself: archive header database, alembic_version
# data, required tables, SHA-256, age. It prints DUMP_SERVER_MAJOR on success.
case "$TARGET" in
    a7c3e91d5b24) REQUIRED_TABLES="alembic_version,financial_rules,rule_executions" ;;
    c4d8a2f6e193) REQUIRED_TABLES="alembic_version,financial_rules,rule_executions,rule_alerts" ;;
esac
ERR_FILE="$(mktemp)" || stop "cannot create a private temporary file"
EVIDENCE_OUT="$("$PY" "$DIR/backup_evidence.py" check-receipt "$BACKUP_EVIDENCE_FILE" "$TARGET" "$EXPECTED_DB" "$PARENT" "$REQUIRED_TABLES" 2>"$ERR_FILE")" \
    || stop "backup evidence rejected: $(head -c 200 "$ERR_FILE" | head -n 1)"
DUMP_MAJOR="$(printf '%s\n' "$EVIDENCE_OUT" | sed -n 's/^DUMP_SERVER_MAJOR=//p')"
[[ "$DUMP_MAJOR" =~ ^[0-9]+$ ]] || stop "backup evidence rejected: unreadable server version"

# --- 2. endpoint proof -------------------------------------------------------------------------
FP_SQL="SELECT (SELECT oid FROM pg_database WHERE datname = current_database()), extract(epoch FROM pg_postmaster_start_time())::bigint, current_database(), current_user, current_setting('lock_timeout'), current_setting('statement_timeout')"

# Both connection paths must reach the same server instance and honour the timeouts. Sets VIA_URL;
# calls stop() (exit 11) itself, so it must not be used inside a command substitution.
take_proof() {
    VIA_PG="$(psql -X -q -At -v ON_ERROR_STOP=1 -c "$FP_SQL" </dev/null 2>/dev/null)" || stop "cannot query the server through the PG* variables"
    VIA_URL="$(cd "$API_DIR" && "$PY" - "$FP_SQL" <<'PY' 2>/dev/null
import os, sys
from sqlalchemy import create_engine, text
with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
    print("|".join(str(value) for value in connection.execute(text(sys.argv[1])).one()))
PY
)" || stop "cannot query the server through DATABASE_URL"

    [ -n "$VIA_PG" ] && [ "$VIA_PG" = "$VIA_URL" ] || stop "the PG* variables and DATABASE_URL do not reach the same server and database"
    IFS='|' read -r _oid _start FP_DB _role FP_LOCK FP_STATEMENT <<<"$VIA_URL"
    [ "$FP_DB" = "$EXPECTED_DB" ] || stop "connected database is not the expected one"
    [ "$FP_LOCK" = "5s" ] || stop "lock_timeout is not 5s on this endpoint (a pooler may have dropped the startup options)"
    [ "$FP_STATEMENT" = "1min" ] || stop "statement_timeout is not 1min on this endpoint (a pooler may have dropped the startup options)"
}

# --- 3. current revision -----------------------------------------------------------------------
check_current() {
    CURRENT="$(cd "$API_DIR" && "$PY" -m alembic current 2>/dev/null)" || stop "alembic current failed"
    CURRENT_REVISIONS="$(printf '%s\n' "$CURRENT" | grep -Eo '^[0-9a-f]{12}' || true)"
    [ "$CURRENT_REVISIONS" = "$PARENT" ] || stop "alembic current is not exactly the parent revision $PARENT"
}

take_proof
FIRST_PROOF="$VIA_URL"

# The dump must come from a server of the same major version as the live one (a cheap server-identity cross-check).
LIVE_MAJOR="$(psql -X -q -At -v ON_ERROR_STOP=1 -c "SELECT current_setting('server_version_num')::int / 10000" </dev/null 2>/dev/null)" || stop "cannot read the server version"
[ "$LIVE_MAJOR" = "$DUMP_MAJOR" ] || stop "the dump was taken from a different PostgreSQL major version than this server"

# --- 2b. serialize concurrent runs (SR-04): one session-level advisory lock held until this process exits ----------
LOCK_STATUS="$(mktemp)" || stop "cannot create a private temporary file"
rm -f "$LOCK_STATUS"
( cd "$API_DIR" && exec "$PY" "$DIR/hold_migration_lock.py" "$LOCK_STATUS" ) >/dev/null 2>&1 &
LOCK_PID=$!
for _wait in $(seq 1 75); do [ -s "$LOCK_STATUS" ] && break; sleep 0.2; done
case "$(cat "$LOCK_STATUS" 2>/dev/null)" in
    LOCKED) ;;
    BUSY)   stop "another guarded migration run holds the lock on this database" ;;
    *)      stop "cannot take the migration lock" ;;
esac
check_current

# --- 4. read-only preflight (the runner refuses DATABASE_URL, so it is removed for the checks only) ---
env -u DATABASE_URL "$DIR/run_readonly_check.sh" "$PREFLIGHT" "$EXPECTED_DB" || stop "the $PREFLIGHT did not PASS"

# --- 4b. repeat the identity and revision proof right before the upgrade (time-of-check window) ----
take_proof
[ "$VIA_URL" = "$FIRST_PROOF" ] || stop "the endpoint changed between the checks and the upgrade (different server instance)"
check_current
kill -0 "$LOCK_PID" 2>/dev/null || stop "the migration lock holder is gone"

# --- 5. the exact upgrade ----------------------------------------------------------------------
echo "applying exactly $TARGET"
( cd "$API_DIR" && "$PY" -m alembic upgrade "$TARGET" ) >/dev/null 2>"$ERR_FILE"
UPGRADE_STATUS=$?
if [ "$UPGRADE_STATUS" -ne 0 ]; then
    # Only FIXED text is printed: Alembic/SQLAlchemy messages can contain hosts, roles, databases or a full URL, so
    # the captured stderr is classified by keyword and never echoed.
    if grep -qiE 'lock timeout' "$ERR_FILE"; then CAUSE="a lock timeout (the table was busy)"
    elif grep -qiE 'statement timeout' "$ERR_FILE"; then CAUSE="a statement timeout"
    elif grep -qiE 'permission denied' "$ERR_FILE"; then CAUSE="a permission error"
    elif grep -qiE 'already exists' "$ERR_FILE"; then CAUSE="an object that already exists"
    elif grep -qiE 'could not (connect|translate)|connection (refused|reset|timed out)|server closed' "$ERR_FILE"; then CAUSE="a connection failure"
    else CAUSE="an unclassified error"; fi
    echo "alembic upgrade failed (exit $UPGRADE_STATUS): $CAUSE. One transaction: nothing was committed. Verify with the preflight." >&2
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
