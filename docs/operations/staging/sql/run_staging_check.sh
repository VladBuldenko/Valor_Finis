#!/usr/bin/env bash
# Read-only STAGING verification runner (VF-QA-1).
#
# Usage:   run_staging_check.sh <app_database_security|supabase_project_exposure> <expected_database_name>
#
# This is NOT the production runner (docs/operations/sql/run_readonly_check.sh), which is unchanged and
# stays the only runner for the E9A/E10 gates. This one exists because that runner cannot be used against
# a dedicated PostgreSQL that has no Supabase roles, and must not be weakened to allow it.
#
#   app_database_security      category A: security posture of the application database FastAPI uses.
#                              Expects EXPECTED_ALEMBIC_REVISION (from `alembic heads`) in the environment.
#   supabase_project_exposure  category B (architecture A): the staging Supabase project's database holds
#                              no application relation, so its Data API has nothing to expose.
#
# Neither check establishes Supabase Data API PARITY with production. The runner says so on every run.
#
# Credentials come ONLY from the libpq environment of the calling shell (PGHOST, PGPORT, PGUSER,
# PGDATABASE and PGPASSWORD or PGPASSFILE). Nothing secret is an argument. PGSERVICE, PGSERVICEFILE,
# PGHOSTADDR and DATABASE_URL are refused: they can silently override the validated target.
#
# Optional environment:
#   APP_ROLE                      database role the API connects as (default: PGUSER); app_database_security only
#   EXPECTED_ALEMBIC_REVISION     required for app_database_security
#   PGSSLROOTCERT                 trust root for verify-full
#   ALLOW_INSECURE_LOCAL_TEST=1   allow a non-TLS connection to localhost / 127.0.0.1 (tests only)
#
# TLS: a remote host needs PGSSLMODE=verify-full (server certificate identity). `require` encrypts but does
# not authenticate the server, so it is refused for anything that is not localhost / 127.0.0.1.
#
# Exit status: 0 = PASS, 10 = STOP (a gating check failed, or the run itself failed), 64 = refused to start.
set -u
set -o pipefail
umask 077

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

refuse() { echo "REFUSED: $1" >&2; exit 64; }

[ "$#" -eq 2 ] || refuse "usage: run_staging_check.sh <app_database_security|supabase_project_exposure> <expected_database_name>"

CHECK="$1"
EXPECTED_DB="$2"

case "$CHECK" in
    app_database_security|supabase_project_exposure) ;;
    *) refuse "unknown check '$CHECK'" ;;
esac

[[ "$EXPECTED_DB" =~ ^[A-Za-z0-9_]+$ ]] || refuse "expected database name must match [A-Za-z0-9_]+"
[ -n "${PGHOST:-}" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGDATABASE:-}" ] || refuse "PGHOST, PGUSER and PGDATABASE must be set in the environment"
[ "$PGDATABASE" = "$EXPECTED_DB" ] || refuse "PGDATABASE does not equal the expected database name"
for forbidden in PGSERVICE PGSERVICEFILE PGHOSTADDR; do
    [ -z "${!forbidden:-}" ] || refuse "unset $forbidden: it can override the validated connection settings"
done
[ -z "${DATABASE_URL:-}" ] || refuse "unset DATABASE_URL: this runner uses the libpq PG* variables only"

LOCAL_HOST=no
case "$PGHOST" in localhost|127.0.0.1) LOCAL_HOST=yes ;; esac

if [ "$LOCAL_HOST" = "yes" ]; then
    case "${PGSSLMODE:-require}" in
        require|verify-ca|verify-full) ;;
        *) [ "${ALLOW_INSECURE_LOCAL_TEST:-}" = "1" ] || refuse "PGSSLMODE must be require, verify-ca or verify-full" ;;
    esac
else
    [ "${PGSSLMODE:-}" = "verify-full" ] || refuse "a remote host needs PGSSLMODE=verify-full (require does not authenticate the server)"
fi

case "$CHECK" in
    app_database_security)
        [[ "$EXPECTED_DB" == *_staging ]] || refuse "app_database_security accepts only a database whose name ends in _staging"
        APP_ROLE="${APP_ROLE:-$PGUSER}"
        [[ "$APP_ROLE" =~ ^[A-Za-z0-9_.-]+$ ]] || refuse "APP_ROLE contains unexpected characters"
        [[ "${EXPECTED_ALEMBIC_REVISION:-}" =~ ^[0-9a-f]{12}$ ]] || refuse "EXPECTED_ALEMBIC_REVISION must be a 12 character revision id (from alembic heads)"
        ;;
    supabase_project_exposure)
        [[ "$EXPECTED_DB" != *_staging && "$EXPECTED_DB" != *_test && "$EXPECTED_DB" != "valor" ]] || refuse "supabase_project_exposure runs against the Supabase project database, not an application database"
        APP_ROLE="unused"
        EXPECTED_ALEMBIC_REVISION="unused"
        ;;
esac

export PGSSLMODE="${PGSSLMODE:-require}"
export PGCONNECT_TIMEOUT=10
export PGAPPNAME="vf-staging-check-$CHECK"
export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=60000"

ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

OUT="$(psql -X -q -v ON_ERROR_STOP=1 \
    -v "expected_db=$EXPECTED_DB" -v "app_role=$APP_ROLE" -v "expected_revision=$EXPECTED_ALEMBIC_REVISION" \
    -P pager=off -P footer=off -f "$DIR/$CHECK.sql" </dev/null 2>"$ERR_FILE")"
STATUS=$?

if [ "$STATUS" -ne 0 ]; then
    FIRST="$(head -n 1 "$ERR_FILE" | sed -E \
        -e 's/"[^"]*"/"<redacted>"/g' -e "s/'[^']*'/'<redacted>'/g" \
        -e 's/\(([0-9a-fA-F:.]+)\)/(<ip>)/g' -e 's/port [0-9]+/port <port>/g' | cut -c1-200)"
    echo "$CHECK: the run did not complete (psql exit $STATUS): ${FIRST:-no message}"
    echo "DATA_API_PARITY: NOT VERIFIED"
    echo "RESULT: STOP"
    exit 10
fi

printf '%s\n' "$OUT"
# A passing run proves what its rows say and nothing about production parity.
echo "DATA_API_PARITY: NOT VERIFIED (this check does not test the Supabase Data API roles or the production hardening)"

if printf '%s\n' "$OUT" | grep -Eq '^ CLASSIFICATION +\| PASS +\|' && ! printf '%s\n' "$OUT" | grep -Eq '\| FAIL +\|'; then
    echo "RESULT: PASS ($CHECK)"
    exit 0
fi

echo "RESULT: STOP ($CHECK)"
exit 10
