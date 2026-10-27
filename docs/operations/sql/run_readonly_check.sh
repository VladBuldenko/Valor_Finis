#!/usr/bin/env bash
# Read-only production verification runner (VF-020E10 OPS-02).
#
# Usage:   run_readonly_check.sh <e9a_preflight|e9a_postcheck|e10_preflight|e10_postcheck> <expected_database_name>
#
# Run it ONLY for a gate the owner has authorized in writing. It never prints
# credentials. Credentials come ONLY from the libpq environment of the calling shell
# (PGHOST, PGPORT, PGUSER, PGDATABASE and PGPASSWORD or PGPASSFILE), which
# the operator loads from the approved secret store. PGSERVICE, PGSERVICEFILE and PGHOSTADDR
# are refused: they can silently override the validated host, TLS mode and options. Nothing secret is ever an
# argument of this script or of psql, so nothing appears in `ps` output or shell history.
#
# Optional environment:
#   APP_ROLE                      the database ROLE the API connects as (default: PGUSER). Behind a
#                                 pooler the login is often 'postgres.<project>': give the role name
#                                 (for example 'postgres'), not the pooler login.
#   DATA_API_ROLES                default anon,authenticated,service_role
#   REQUIRE_DATA_API_ROLES        default yes; 'no' ONLY for a local database without them
#   ALLOW_INSECURE_LOCAL_TEST=1   allow a non-TLS connection to localhost (tests only)
#
# Safety: the session is READ ONLY at three levels (default_transaction_read_only,
# BEGIN READ ONLY in the script, no write statement in the scripts), with bounded
# statement / lock / idle-in-transaction timeouts and a connect timeout. It uses
# fail-fast SQL (ON_ERROR_STOP) and the script always ROLLBACKs. It selects catalog
# metadata and counts only, never customer rows.
#
# Exit status: 0 = PASS, 10 = STOP (a gating check failed, or the run itself failed),
# 64 = usage / refused to start.
set -u
set -o pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

refuse() { echo "REFUSED: $1" >&2; exit 64; }

[ "$#" -eq 2 ] || refuse "usage: run_readonly_check.sh <e9a_preflight|e9a_postcheck|e10_preflight|e10_postcheck> <expected_database_name>"

CHECK="$1"
EXPECTED_DB="$2"

case "$CHECK" in
    e9a_preflight|e9a_postcheck|e10_preflight|e10_postcheck) ;;
    *) refuse "unknown check '$CHECK'" ;;
esac

[[ "$EXPECTED_DB" =~ ^[A-Za-z0-9_]+$ ]] || refuse "expected database name must match [A-Za-z0-9_]+"
[ -n "${PGHOST:-}" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGDATABASE:-}" ] || refuse "PGHOST, PGUSER and PGDATABASE must be set in the environment"
[ "$PGDATABASE" = "$EXPECTED_DB" ] || refuse "PGDATABASE does not equal the expected database name"
# libpq lets a service file or a numeric host address override the validated PG* variables, which
# would defeat the host, TLS and option checks below. Refuse them instead of trusting them.
for forbidden in PGSERVICE PGSERVICEFILE PGHOSTADDR; do
    [ -z "${!forbidden:-}" ] || refuse "unset $forbidden: it can override the validated connection settings"
done
[ -z "${DATABASE_URL:-}" ] || refuse "unset DATABASE_URL: this runner uses the libpq PG* variables only"

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

DATA_API_ROLES="${DATA_API_ROLES:-anon,authenticated,service_role}"
REQUIRE_ROLES="${REQUIRE_DATA_API_ROLES:-yes}"
APP_ROLE="${APP_ROLE:-$PGUSER}"
LOCAL_HOST=no
case "$PGHOST" in localhost|127.0.0.1|/*) LOCAL_HOST=yes ;; esac
# Weakening the privilege checks is allowed only against a local test database: on a remote
# host a PASS must really have tested the Supabase Data API roles.
if [ "$LOCAL_HOST" != "yes" ]; then
    [ "$REQUIRE_ROLES" = "yes" ] || refuse "REQUIRE_DATA_API_ROLES=no is allowed only for a local database"
    [ "$DATA_API_ROLES" = "anon,authenticated,service_role" ] || refuse "DATA_API_ROLES may be changed only for a local database"
elif [ "$REQUIRE_ROLES" = "no" ] || [ "$DATA_API_ROLES" != "anon,authenticated,service_role" ]; then
    # A tunnel to production also looks local: weakening the checks needs a *_test database.
    [[ "$EXPECTED_DB" == *_test ]] || refuse "weakened privilege checks are allowed only for a database whose name ends in _test"
fi
[[ "$DATA_API_ROLES" =~ ^[a-z_]+(,[a-z_]+)*$ ]] || refuse "DATA_API_ROLES must be a comma separated list of role names"
[[ "$APP_ROLE" =~ ^[A-Za-z0-9_.-]+$ ]] || refuse "APP_ROLE contains unexpected characters"
[ "$REQUIRE_ROLES" = "yes" ] || [ "$REQUIRE_ROLES" = "no" ] || refuse "REQUIRE_DATA_API_ROLES must be yes or no"

export PGSSLMODE="${PGSSLMODE:-require}"
export PGCONNECT_TIMEOUT=10
export PGAPPNAME="vf-readonly-check-$CHECK"
# Replaces any inherited PGOPTIONS. A pooler that rejects startup options must not be
# used for this runner: use the direct or session-mode endpoint instead.
export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=60000"

ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

OUT="$(psql -X -q -v ON_ERROR_STOP=1 \
    -v "expected_db=$EXPECTED_DB" -v "app_role=$APP_ROLE" \
    -v "data_api_roles=$DATA_API_ROLES" -v "require_roles=$REQUIRE_ROLES" \
    -P pager=off -P footer=off -f "$DIR/$CHECK.sql" </dev/null 2>"$ERR_FILE")"
STATUS=$?

if [ "$STATUS" -ne 0 ]; then
    # Only the first error line, with connection details removed.
    FIRST="$(head -n 1 "$ERR_FILE" | sed -E \
        -e 's/"[^"]*"/"<redacted>"/g' -e "s/'[^']*'/'<redacted>'/g" \
        -e 's/\(([0-9a-fA-F:.]+)\)/(<ip>)/g' -e 's/port [0-9]+/port <port>/g' | cut -c1-200)"
    echo "$CHECK: the run did not complete (psql exit $STATUS): ${FIRST:-no message}"
    echo "RESULT: STOP"
    exit 10
fi

printf '%s\n' "$OUT"

# PASS needs the CLASSIFICATION row AND no FAIL row anywhere (defence in depth).
if printf '%s\n' "$OUT" | grep -Eq '^ CLASSIFICATION +\| PASS +\|' && ! printf '%s\n' "$OUT" | grep -Eq '\| FAIL +\|'; then
    echo "RESULT: PASS ($CHECK)"
    exit 0
fi

echo "RESULT: STOP ($CHECK)"
exit 10
