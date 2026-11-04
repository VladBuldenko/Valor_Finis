-- VF-QA-1 staging: READ-ONLY exposure check of the staging SUPABASE PROJECT database (category B, architecture A).
--
-- Run it ONLY through run_staging_check.sh against the database of the STAGING SUPABASE PROJECT
-- (normally named postgres), never against the application database. Required psql variable: expected_db.
--
-- Question answered: does the Supabase Data API (PostgREST) of the staging project have any application
-- data to expose? Under architecture A (Supabase project for Auth and Storage only, application tables in
-- a separate PostgreSQL) the answer must be no: schema public holds no relation that no extension owns.
-- This is an EXPOSURE check. It is NOT parity with the production hardening (migration edcfdf3f7114): that
-- hardening revokes privileges on the application tables, and there are none here to revoke.
--
-- READ ONLY, rolled back, bounded timeouts, catalog metadata only (no row content).
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
public_relations AS (
    SELECT c.oid, c.relname, c.relkind
    FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
),
public_functions AS (
    SELECT p.oid FROM pg_proc p
    WHERE p.pronamespace = 'public'::regnamespace
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
),
supabase_roles AS (
    SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
),
checks(ord, check_name, gating, ok, expected, actual) AS (
    VALUES
    (1, 'transaction_read_only', true,
        current_setting('transaction_read_only') = 'on', 'on', current_setting('transaction_read_only')),
    (2, 'database_name', true,
        current_database() = :'expected_db', :'expected_db', current_database()),
    (3, 'not_an_application_database', true,
        current_database() NOT LIKE '%\_staging' AND current_database() NOT LIKE '%\_test' AND current_database() <> 'valor',
        'a Supabase project database, not the application database', current_database()),
    (4, 'no_alembic_version_table', true,
        to_regclass('public.alembic_version') IS NULL, 'absent', CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 'absent' ELSE 'present' END),
    (5, 'no_application_relations_in_public', true,
        NOT EXISTS (SELECT 1 FROM public_relations), '0', (SELECT count(*)::text FROM public_relations)),
    (6, 'no_application_functions_in_public', true,
        NOT EXISTS (SELECT 1 FROM public_functions), '0', (SELECT count(*)::text FROM public_functions)),
    (7, 'supabase_data_api_roles_present', false, false, 'informational only',
        (SELECT count(*)::text FROM supabase_roles) || ' of 3'),
    (8, 'server_version', false, false, '-', split_part(version(), ' on ', 1))
)
SELECT check_name, status, expected, actual FROM (
    SELECT ord, check_name,
           CASE WHEN coalesce(ok, false) THEN 'OK' WHEN gating THEN 'FAIL' ELSE 'INFO' END AS status,
           expected, actual
    FROM checks
    UNION ALL
    SELECT 999, 'CLASSIFICATION',
           CASE WHEN bool_and(coalesce(ok, false) OR NOT gating) THEN 'PASS' ELSE 'STOP' END,
           'every gating check OK', count(*) FILTER (WHERE gating AND NOT coalesce(ok, false)) || ' gating failure(s)'
    FROM checks
) AS report
ORDER BY ord;

ROLLBACK;
