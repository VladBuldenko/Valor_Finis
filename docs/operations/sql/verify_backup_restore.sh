#!/usr/bin/env bash
# Backup restore verifier (VF-OPS03-1 remediation SR-01/SR-02).
#
# Usage:   RESTORE_PGHOST=localhost RESTORE_PGUSER=<role that may CREATE DATABASE> [RESTORE_PGPORT=] [RESTORE_PGPASSWORD=] \
#          verify_backup_restore.sh <a7c3e91d5b24|c4d8a2f6e193> <expected_database_name> <dump_file> <receipt_out>
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
# What this does NOT prove: that the dump came from the production SERVER (the archive records the database name,
# not the server; a same-named database elsewhere with the same revision is indistinguishable), and the receipt seal
# is a checksum, not a signature (a dishonest operator can forge it). See docs/operations/e9a-production-migration.md
# section 4 for the owner's risk acceptance.
#
# Exit: 0 = receipt written; 1 = verification failed (no receipt); 64 = refused to start.
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
[ -n "${RESTORE_PGHOST:-}" ] && [ -n "${RESTORE_PGUSER:-}" ] || refuse "RESTORE_PGHOST and RESTORE_PGUSER must be set"
case "$RESTORE_PGHOST" in
    localhost|127.0.0.1|/*) ;;
    *) refuse "the restore server must be local (localhost, 127.0.0.1 or a socket directory)" ;;
esac
for tool in psql createdb dropdb pg_restore python3; do
    command -v "$tool" >/dev/null 2>&1 || refuse "$tool is required"
done

# Clean environment: only RESTORE_PG* reaches the child programs.
clean() {
    env -i PATH="$PATH" HOME="${HOME:-/}" PGHOST="$RESTORE_PGHOST" PGPORT="${RESTORE_PGPORT:-5432}" \
        PGUSER="$RESTORE_PGUSER" PGPASSWORD="${RESTORE_PGPASSWORD:-}" PGCONNECT_TIMEOUT=10 PGSSLMODE="${RESTORE_PGSSLMODE:-prefer}" "$@"
}

# 1. dump facts (no database involved)
FACTS="$(python3 "$DIR/backup_evidence.py" inspect-dump "$DUMP" "$EXPECTED_DB" "$SOURCE" "$TABLES" 2>&1)" || fail "$FACTS"
fact() { printf '%s\n' "$FACTS" | sed -n "s/^$1=//p"; }

# 2-3. throwaway database on the local server and restore
RESTORE_DB="vf_restore_$(date +%s)_${RANDOM}_test"
[[ "$RESTORE_DB" =~ ^vf_restore_[0-9]+_[0-9]+_test$ ]] || fail "internal: unexpected throwaway name"
[ "$RESTORE_DB" != "$EXPECTED_DB" ] || fail "internal: the throwaway database equals the expected database"
cleanup() { clean dropdb --if-exists "$RESTORE_DB" >/dev/null 2>&1; }
trap cleanup EXIT
clean createdb "$RESTORE_DB" >/dev/null 2>&1 || fail "cannot create the throwaway database on the local server"
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
clean PGDATABASE="$RESTORE_DB" REQUIRE_DATA_API_ROLES=no PGSSLMODE=disable ALLOW_INSECURE_LOCAL_TEST=1 \
    "$DIR/run_readonly_check.sh" "$PREFLIGHT" "$RESTORE_DB" >/dev/null 2>&1 || fail "the $PREFLIGHT did not PASS on the restored copy"

# 6. sealed receipt
python3 "$DIR/backup_evidence.py" write-receipt "$RECEIPT" \
    "GATE_TARGET=$TARGET" "DATABASE=$EXPECTED_DB" "SOURCE_REVISION=$SOURCE" "DUMP_FILE=$DUMP" \
    "DUMP_SHA256=$(fact DUMP_SHA256)" "DUMP_DBNAME=$(fact DUMP_DBNAME)" "DUMP_SERVER_MAJOR=$(fact DUMP_SERVER_MAJOR)" \
    "DUMP_CREATED_AT_UTC=$(fact DUMP_CREATED_AT_UTC)" "RESTORE_DATABASE=$RESTORE_DB" "RESTORE_REVISION=$RESTORED_REVISION" \
    "RESTORE_PREFLIGHT=PASS" "RESTORE_SERVER_MAJOR=$RESTORE_MAJOR" "RESTORE_VERIFIED_AT_UTC=$(date -u +%Y%m%dT%H%M%SZ)" \
    "RECEIPT_SEAL=" >/dev/null 2>&1 || fail "cannot write the receipt"
echo "RECEIPT WRITTEN: restore and $PREFLIGHT verified on a throwaway database"
exit 0
