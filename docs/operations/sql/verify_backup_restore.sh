#!/usr/bin/env bash
# Backup restore verifier (VF-OPS03-1 remediation SR-01/SR-02).
#
# Usage:   RESTORE_PGHOST=<local socket directory> RESTORE_PGDATA=<that server's data directory> \
#          RESTORE_PGUSER=<role that may CREATE DATABASE> [RESTORE_PGPORT=] [RESTORE_PGPASSWORD=] \
#          verify_backup_restore.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name> <dump_file> <receipt_out>
#          (TCP to localhost/127.0.0.1 is accepted only with RESTORE_ALLOW_LOOPBACK_TCP=1; see "Local server proof".)
#
# Run it on the operator's LOCAL machine against a LOCAL disposable PostgreSQL server, never against production.
# It performs the restore and the read-only preflight itself and writes the receipt that run_guarded_migration.sh
# demands. Nothing is attested by hand:
#   1. the dump is inspected (backup_evidence.py inspect-dump): its archive header names the database it came from (must
#      be the expected one), its alembic_version DATA holds exactly the source revision of the gate, required tables listed;
#   2. a throwaway `vf_restore_*_test` database is created on the LOCAL server (RESTORE_PG* only; every PG*/DATABASE_URL
#      variable of the operator's shell is dropped, so a production connection cannot be reached by accident);
#   3. the dump is restored into it with pg_restore --clean --if-exists --exit-on-error (as in the runbook);
#   4. the restored alembic_version is read back and must equal the source revision;
#   5. the read-only preflight of the gate runs on the restored copy and must PASS (REQUIRE_DATA_API_ROLES=no: the Data
#      API roles do not exist locally; the privilege checks that need them are validated on production by the runner);
#   6. only then the sealed receipt is written (mode 600, written atomically; none is left on any failure) and the
#      throwaway database is dropped on exit, success or failure.
#
# Local server proof (SR-08), run BEFORE anything is created: "localhost" can be an SSH tunnel to a remote server and
# environment scrubbing proves nothing about identity, so the script requires that the server it reached is the
# postmaster whose postmaster.pid lives in RESTORE_PGDATA on THIS machine: that file's pid must be a running local process,
# its recorded port must equal the port, its data directory must equal RESTORE_PGDATA, and its recorded start time must
# equal the start time the reached server reports (pg_postmaster_start_time(), +-2 s). A socket directory (absolute
# RESTORE_PGHOST) is preferred and must contain the socket file; loopback TCP needs RESTORE_ALLOW_LOOPBACK_TCP=1.
# Limit that cannot be removed automatically: a remote server could in theory be forwarded onto this machine's socket AND
# have a start time equal to a local postmaster's to the second; that is not defended against.
#
# What this does NOT prove: that the dump came from the production SERVER (the archive records the database name,
# not the server; a same-named database elsewhere with the same revision is indistinguishable), and the receipt seal
# is a checksum, not a signature (a dishonest operator can forge it). See docs/operations/e9a-production-migration.md
# section 4 for the owner's risk acceptance.
#
# Cleanup (SR-05/SR-06): the throwaway database is dropped only if THIS run created it (a failed createdb, e.g. because
# the name exists, never leads to a dropdb). The receipt is written to a pending path, the database is dropped and the
# drop is CHECKED, and only then is the receipt moved into place: if the drop fails there is no receipt, the exit status
# is 1 and the message names the database for manual investigation.
#
# Exit: 0 = receipt written; 1 = verification failed or cleanup failed (no receipt); 64 = refused to start.
set -u
set -o pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
refuse() { echo "REFUSED: $1" >&2; exit 64; }
fail() { echo "VERIFICATION FAILED: $1" >&2; exit 1; }

[ "$#" -eq 4 ] || refuse "usage: verify_backup_restore.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name> <dump_file> <receipt_out>"
TARGET="$1"; EXPECTED_DB="$2"; DUMP="$3"; RECEIPT="$4"
case "$TARGET" in
    a7c3e91d5b24) SOURCE="e0503e9ca9d3"; PREFLIGHT="e9a_preflight"; TABLES="alembic_version,financial_rules,rule_executions" ;;
    c4d8a2f6e193) SOURCE="a7c3e91d5b24"; PREFLIGHT="e10_preflight"; TABLES="alembic_version,financial_rules,rule_executions,rule_alerts" ;;
    *) refuse "only revisions a7c3e91d5b24 and c4d8a2f6e193 are supported" ;;
esac
[[ "$EXPECTED_DB" =~ ^[A-Za-z0-9_]+$ ]] || refuse "expected database name must match [A-Za-z0-9_]+"
case "$DUMP" in /*) ;; *) refuse "the dump path must be absolute" ;; esac
case "$RECEIPT" in /*) ;; *) refuse "the receipt path must be absolute" ;; esac
[ ! -e "$RECEIPT" ] || refuse "the receipt path already exists"
[ -n "${RESTORE_PGHOST:-}" ] && [ -n "${RESTORE_PGUSER:-}" ] && [ -n "${RESTORE_PGDATA:-}" ] \
    || refuse "RESTORE_PGHOST, RESTORE_PGUSER and RESTORE_PGDATA (the local server's data directory) must be set"
case "$RESTORE_PGHOST" in
    /*) [ -d "$RESTORE_PGHOST" ] || refuse "RESTORE_PGHOST must be an existing socket directory" ;;
    localhost|127.0.0.1)
        [ "${RESTORE_ALLOW_LOOPBACK_TCP:-}" = "1" ] \
            || refuse "loopback TCP can be a tunnel to a remote server: prefer a socket directory, or set RESTORE_ALLOW_LOOPBACK_TCP=1 (the local server proof still applies)" ;;
    *) refuse "the restore server must be local: a socket directory, or localhost/127.0.0.1 with RESTORE_ALLOW_LOOPBACK_TCP=1" ;;
esac
case "${RESTORE_PGPORT:-5432}" in ''|*[!0-9]*) refuse "RESTORE_PGPORT must be a number" ;; esac
case "$RESTORE_PGDATA" in /*) ;; *) refuse "RESTORE_PGDATA must be an absolute path" ;; esac
[ -r "$RESTORE_PGDATA/postmaster.pid" ] || refuse "RESTORE_PGDATA does not contain a readable postmaster.pid (is the server local and running?)"
case "$RESTORE_PGHOST" in
    /*) [ -S "$RESTORE_PGHOST/.s.PGSQL.${RESTORE_PGPORT:-5432}" ] || refuse "no PostgreSQL socket file in RESTORE_PGHOST for this port" ;;
esac
for tool in psql createdb dropdb pg_restore python3; do
    command -v "$tool" >/dev/null 2>&1 || refuse "$tool is required"
done

# Clean environment: only RESTORE_PG* reaches the child programs.
clean() {
    env -i PATH="$PATH" HOME="${HOME:-/}" PGHOST="$RESTORE_PGHOST" PGPORT="${RESTORE_PGPORT:-5432}" \
        PGUSER="$RESTORE_PGUSER" ${RESTORE_PGPASSWORD:+"PGPASSWORD=$RESTORE_PGPASSWORD"} PGCONNECT_TIMEOUT=10 PGSSLMODE="${RESTORE_PGSSLMODE:-prefer}" "$@"
}

# 1. dump facts (no database involved)
FACTS="$(python3 "$DIR/backup_evidence.py" inspect-dump "$DUMP" "$EXPECTED_DB" "$SOURCE" "$TABLES" 2>&1)" || fail "$FACTS"
fact() { printf '%s\n' "$FACTS" | sed -n "s/^$1=//p"; }

# 2. local server proof (before anything is created)
SERVER_START="$(clean psql -X -q -At -d template1 -c "SELECT extract(epoch FROM pg_postmaster_start_time())::bigint" 2>/dev/null)" \
    || fail "cannot connect to the restore server"
[[ "$SERVER_START" =~ ^[0-9]+$ ]] || fail "unexpected answer from the restore server"
PID_LINES="$(sed -n '1,4p' "$RESTORE_PGDATA/postmaster.pid" 2>/dev/null)"
PM_PID="$(printf '%s\n' "$PID_LINES" | sed -n 1p)"; PM_DIR="$(printf '%s\n' "$PID_LINES" | sed -n 2p)"
PM_START="$(printf '%s\n' "$PID_LINES" | sed -n 3p)"; PM_PORT="$(printf '%s\n' "$PID_LINES" | sed -n 4p)"
[[ "$PM_PID" =~ ^[0-9]+$ ]] && [[ "$PM_START" =~ ^[0-9]+$ ]] || fail "postmaster.pid is not in the expected format"
kill -0 "$PM_PID" 2>/dev/null || fail "the postmaster named in RESTORE_PGDATA is not a running local process"
[ "$PM_DIR" = "$RESTORE_PGDATA" ] || fail "RESTORE_PGDATA does not match the data directory recorded in postmaster.pid"
[ "$PM_PORT" = "${RESTORE_PGPORT:-5432}" ] || fail "the local postmaster listens on a different port than the one used"
SKEW=$(( SERVER_START - PM_START )); [ "${SKEW#-}" -le 2 ] || fail "the server reached is not the local postmaster of RESTORE_PGDATA (start times differ): possible tunnel"

# 3. throwaway database and restore. CREATED stays "no" unless createdb itself succeeded: an existing database of that
# name (or any createdb failure) is never dropped, here or by the exit trap.
RESTORE_DB="vf_restore_$(date +%s)_${RANDOM}_test"
[[ "$RESTORE_DB" =~ ^vf_restore_[0-9]+_[0-9]+_test$ ]] || fail "internal: unexpected throwaway name"
[ "$RESTORE_DB" != "$EXPECTED_DB" ] || fail "internal: the throwaway database equals the expected database"
CREATED=no
drop_throwaway() {
    [ "$CREATED" = "yes" ] || return 0
    if clean dropdb "$RESTORE_DB" >/dev/null 2>&1; then CREATED=no; return 0; fi
    return 1
}
cleanup() {
    if ! drop_throwaway; then
        echo "CLEANUP FAILED: the temporary database $RESTORE_DB may still exist on the local server and needs manual investigation." >&2
        rm -f "$RECEIPT" "$PENDING"
        trap - EXIT; exit 1
    fi
    rm -f "$PENDING"
}
PENDING="$RECEIPT.pending.$$"
trap cleanup EXIT
trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
clean createdb "$RESTORE_DB" >/dev/null 2>&1 || fail "cannot create the throwaway database (nothing was dropped)"
CREATED=yes
clean pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname="$RESTORE_DB" "$DUMP" >/dev/null 2>&1 \
    || fail "pg_restore into the throwaway database failed"

# 4. restored revision
RESTORED_REVISION="$(clean psql -X -q -At -d "$RESTORE_DB" -c "SELECT string_agg(version_num, ',') FROM alembic_version" 2>/dev/null)" \
    || fail "cannot read the restored alembic_version"
[ "$RESTORED_REVISION" = "$SOURCE" ] || fail "the restored database is not at the source revision"
RESTORE_MAJOR="$(clean psql -X -q -At -d "$RESTORE_DB" -c "SELECT current_setting('server_version_num')::int / 10000" 2>/dev/null)" \
    || fail "cannot read the restore server version"
[[ "$RESTORE_MAJOR" =~ ^[0-9]+$ ]] || fail "unexpected restore server version"

# 5. read-only preflight on the restored copy
# (libpq ignores sslmode on a Unix socket, so "require" satisfies the wrapper's TLS rule there; TCP needs the local-test flag)
PREFLIGHT_SSL=disable; case "$RESTORE_PGHOST" in /*) PREFLIGHT_SSL=require ;; esac
clean PGDATABASE="$RESTORE_DB" REQUIRE_DATA_API_ROLES=no PGSSLMODE="$PREFLIGHT_SSL" ALLOW_INSECURE_LOCAL_TEST=1 \
    "$DIR/run_readonly_check.sh" "$PREFLIGHT" "$RESTORE_DB" >/dev/null 2>&1 || fail "the $PREFLIGHT did not PASS on the restored copy"

# 6. sealed receipt: written to a pending path, the throwaway is dropped and the drop CHECKED, only then moved into place
python3 "$DIR/backup_evidence.py" write-receipt "$PENDING" \
    "GATE_TARGET=$TARGET" "DATABASE=$EXPECTED_DB" "SOURCE_REVISION=$SOURCE" "DUMP_FILE=$DUMP" \
    "DUMP_SHA256=$(fact DUMP_SHA256)" "DUMP_DBNAME=$(fact DUMP_DBNAME)" "DUMP_SERVER_MAJOR=$(fact DUMP_SERVER_MAJOR)" \
    "DUMP_CREATED_AT_UTC=$(fact DUMP_CREATED_AT_UTC)" "RESTORE_DATABASE=$RESTORE_DB" "RESTORE_REVISION=$RESTORED_REVISION" \
    "RESTORE_PREFLIGHT=PASS" "RESTORE_SERVER_MAJOR=$RESTORE_MAJOR" "RESTORE_VERIFIED_AT_UTC=$(date -u +%Y%m%dT%H%M%SZ)" \
    "RECEIPT_SEAL=" >/dev/null 2>&1 || fail "cannot write the receipt"
drop_throwaway || { echo "CLEANUP FAILED: the temporary database $RESTORE_DB may still exist on the local server and needs manual investigation. No receipt was kept." >&2; rm -f "$PENDING"; trap - EXIT; exit 1; }
mv "$PENDING" "$RECEIPT" || { rm -f "$PENDING" "$RECEIPT"; fail "cannot place the receipt"; }
echo "RECEIPT WRITTEN: restore and $PREFLIGHT verified on a throwaway database (dropped)"
exit 0
