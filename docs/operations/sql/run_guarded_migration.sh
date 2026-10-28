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
#   1b. backup evidence: BACKUP_EVIDENCE_FILE must be a strict receipt bound to THIS target, database and
#      source revision; the dump it names must exist, match its SHA-256, list the required tables, and the
#      dump and the restore verification must be younger than 24 h (see the E9A runbook section 4);
#   2. endpoint proof: the PG* path and the DATABASE_URL path must reach the SAME database
#      server (same database oid, same postmaster start time, same database name = the expected
#      one, same role) and BOTH must honour lock_timeout = 5s and statement_timeout = 1min;
#   3. `alembic current` must report exactly the parent revision;
#   4. the read-only preflight of the target must PASS;
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
# MIGRATION_PYTHON (the interpreter used for the proof and for Alembic) exists for the disposable-database
# tests only and is refused for any other database; production use leaves it unset.
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
LOCAL_TEST_MODE=no
if [ "${ALLOW_INSECURE_LOCAL_TEST:-}" = "1" ] && { [ "$PGHOST" = "localhost" ] || [ "$PGHOST" = "127.0.0.1" ]; }; then
    LOCAL_TEST_MODE=yes
fi
# MIGRATION_PYTHON replaces the interpreter that runs the evidence check, the endpoint proof and Alembic, so it would
# bypass every guard: it is honoured only in the disposable local test mode, never for a real database.
[ -z "${MIGRATION_PYTHON:-}" ] || [ "$LOCAL_TEST_MODE" = "yes" ] || refuse "MIGRATION_PYTHON is only accepted for disposable local test databases"
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
        [ "$LOCAL_TEST_MODE" = "yes" ] || refuse "PGSSLMODE must be require, verify-ca or verify-full"
        ;;
esac
export PGSSLMODE="${PGSSLMODE:-require}"

export PGCONNECT_TIMEOUT=10
export PGAPPNAME="vf-guarded-migration-$TARGET"
export PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=60000"

# --- 1b. backup evidence (local files only; no database is contacted) --------------------------
case "$TARGET" in
    a7c3e91d5b24) REQUIRED_TABLES="alembic_version,financial_rules,rule_executions" ;;
    c4d8a2f6e193) REQUIRED_TABLES="alembic_version,financial_rules,rule_executions,rule_alerts" ;;
esac
EVIDENCE_ERROR="$("$PY" - "$BACKUP_EVIDENCE_FILE" "$TARGET" "$EXPECTED_DB" "$PARENT" "$REQUIRED_TABLES" <<'PY' 2>&1 >/dev/null
import hashlib, os, re, stat, subprocess, sys, time
from datetime import datetime, timezone

sys.excepthook = lambda *_: (print("unexpected error while verifying the evidence", file=sys.stderr), os._exit(1))
path, target, database, source, tables = sys.argv[1:6]
MAX_AGE, SKEW = 24 * 3600, 300
KEYS = ("GATE_TARGET", "DATABASE", "SOURCE_REVISION", "DUMP_FILE", "DUMP_SHA256", "DUMP_TAKEN_AT_UTC",
        "RESTORE_VERIFIED", "RESTORE_DATABASE", "RESTORE_PREFLIGHT", "RESTORE_VERIFIED_AT_UTC")


def fail(reason):
    print(reason, file=sys.stderr)
    sys.exit(1)


def regular_own_file(candidate, what, private):
    try:
        info = os.lstat(candidate)
    except OSError:
        fail("%s is missing or unreadable" % what)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        fail("%s must be a regular file owned by the operator (no symlink)" % what)
    if info.st_mode & (0o077 if private else 0o022):
        fail("%s has unsafe permissions" % what)
    return info


def moment(value, name):
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        fail("%s is not a UTC timestamp like 20261028T101500Z" % name)


now = time.time()
receipt = regular_own_file(path, "the evidence receipt", False)
if not 0 < receipt.st_size <= 4096:
    fail("the evidence receipt is empty or too large")
fields = {}
for line in os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8").read().splitlines():
    if not line.strip():
        continue
    key, separator, value = line.partition("=")
    if not separator or key not in KEYS or key in fields or value != value.strip() or not value:
        fail("the evidence receipt has an unknown, duplicate or malformed line")
    fields[key] = value
if sorted(fields) != sorted(KEYS):
    fail("the evidence receipt does not contain exactly the required fields")

if fields["GATE_TARGET"] != target or fields["DATABASE"] != database or fields["SOURCE_REVISION"] != source:
    fail("the receipt is not bound to this target, database and source revision")
if fields["RESTORE_VERIFIED"] != "PASS" or fields["RESTORE_PREFLIGHT"] != "PASS":
    fail("the receipt does not record a PASSed restore verification")
restore_database = fields["RESTORE_DATABASE"]
if not re.fullmatch(r"[A-Za-z0-9_]+_test", restore_database) or restore_database == database:
    fail("the restore must have been verified on a throwaway *_test database, never the target")

taken, verified = moment(fields["DUMP_TAKEN_AT_UTC"], "DUMP_TAKEN_AT_UTC"), moment(fields["RESTORE_VERIFIED_AT_UTC"], "RESTORE_VERIFIED_AT_UTC")
if taken > now + SKEW or verified > now + SKEW or verified < taken:
    fail("the receipt timestamps are inconsistent")
if now - taken > MAX_AGE or now - verified > MAX_AGE:
    fail("the backup evidence is older than 24 hours: take and verify a fresh backup")

dump = fields["DUMP_FILE"]
if not os.path.isabs(dump):
    fail("DUMP_FILE must be an absolute path")
info = regular_own_file(dump, "the dump file", True)
if info.st_size < 4096:
    fail("the dump file is trivially small")
if now - info.st_mtime > MAX_AGE or info.st_mtime > now + SKEW:
    fail("the dump file is not from the last 24 hours")
digest = hashlib.sha256()
with os.fdopen(os.open(dump, os.O_RDONLY | os.O_NOFOLLOW), "rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
if digest.hexdigest() != fields["DUMP_SHA256"].lower():
    fail("the dump file does not match its recorded SHA-256")
listing = subprocess.run(["pg_restore", "--list", dump], capture_output=True, text=True)
if listing.returncode != 0:
    fail("pg_restore cannot read the dump file")
present = set(re.findall(r"\bTABLE public (\w+) ", listing.stdout))
missing = [name for name in tables.split(",") if name not in present]
if missing:
    fail("the dump does not list the required tables: " + ",".join(missing))
PY
)" || stop "backup evidence rejected: ${EVIDENCE_ERROR:-unspecified}"

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
check_current

# --- 4. read-only preflight (the runner refuses DATABASE_URL, so it is removed for the checks only) ---
env -u DATABASE_URL "$DIR/run_readonly_check.sh" "$PREFLIGHT" "$EXPECTED_DB" || stop "the $PREFLIGHT did not PASS"

# --- 4b. repeat the identity and revision proof right before the upgrade (time-of-check window) ----
take_proof
[ "$VIA_URL" = "$FIRST_PROOF" ] || stop "the endpoint changed between the checks and the upgrade (different server instance)"
check_current

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
