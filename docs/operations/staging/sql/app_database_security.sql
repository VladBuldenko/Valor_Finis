-- VF-QA-1 staging: READ-ONLY application database security checks (category A).
--
-- Run it ONLY through run_staging_check.sh. Required psql variables: expected_db, app_role,
-- expected_revision.
--
-- Scope: the dedicated PostgreSQL database the FastAPI backend connects to. These checks
-- say NOTHING about the Supabase Data API: whether the roles anon, authenticated and
-- service_role exist is reported as INFO only, and the wrapper always prints
-- "DATA_API_PARITY: NOT VERIFIED". A PASS here is never evidence of Data API parity.
--
-- READ ONLY, rolled back, bounded timeouts, catalog metadata only (no row content).
-- Output: one row per check (OK / FAIL / INFO) and a final CLASSIFICATION row. INFO rows never gate.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
app AS (SELECT * FROM pg_roles WHERE rolname = :'app_role'),
app_relations AS (
    -- Ordinary tables and sequences in public that no extension owns.
    SELECT c.oid, c.relname, c.relkind, c.relacl, c.relowner
    FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'S')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
),
public_grants AS (
    -- Grantee 0 in an ACL is PUBLIC. A NULL relacl means the default ACL (owner only).
    SELECT r.relname, a.privilege_type
    FROM app_relations r,
         aclexplode(coalesce(r.relacl, acldefault((CASE r.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", r.relowner))) a
    WHERE a.grantee = 0
),
other_grantees AS (
    SELECT string_agg(DISTINCT pg_get_userbyid(a.grantee), ',') AS names
    FROM app_relations r,
         aclexplode(coalesce(r.relacl, acldefault((CASE r.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", r.relowner))) a
    WHERE a.grantee <> 0 AND a.grantee <> r.relowner AND pg_get_userbyid(a.grantee) <> :'app_role'
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
    (3, 'database_name_ends_staging', true,
        current_database() LIKE '%\_staging', '*_staging', current_database()),
    (4, 'server_is_primary', true,
        NOT pg_is_in_recovery(), 'primary', CASE WHEN pg_is_in_recovery() THEN 'standby' ELSE 'primary' END),
    (5, 'alembic_version_single_row', true,
        (SELECT count(*) FROM alembic_version) = 1, '1', (SELECT count(*)::text FROM alembic_version)),
    (6, 'alembic_revision_equals_expected', true,
        (SELECT min(version_num) FROM alembic_version) = :'expected_revision', :'expected_revision',
        coalesce((SELECT min(version_num) FROM alembic_version), '<none>')),
    (7, 'application_tables_present', true,
        (SELECT count(*) FROM app_relations WHERE relkind IN ('r', 'p')) > 0, 'at least one', (SELECT count(*)::text FROM app_relations WHERE relkind IN ('r', 'p'))),
    (8, 'application_role_exists', true,
        EXISTS (SELECT 1 FROM app), 'true', EXISTS (SELECT 1 FROM app)::text),
    (9, 'application_role_is_not_superuser', true,
        coalesce((SELECT NOT rolsuper FROM app), false), 'false', coalesce((SELECT rolsuper::text FROM app), '<missing>')),
    (10, 'application_role_cannot_bypass_rls_or_create_roles_or_databases', true,
        coalesce((SELECT NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb FROM app), false),
        'bypassrls=false createrole=false createdb=false',
        coalesce((SELECT 'bypassrls=' || rolbypassrls || ' createrole=' || rolcreaterole || ' createdb=' || rolcreatedb FROM app), '<missing>')),
    (11, 'application_role_can_use_every_application_table', true,
        coalesce((SELECT bool_and(has_table_privilege(:'app_role', oid, 'SELECT') AND has_table_privilege(:'app_role', oid, 'INSERT')
                                  AND has_table_privilege(:'app_role', oid, 'UPDATE') AND has_table_privilege(:'app_role', oid, 'DELETE'))
                  FROM app_relations WHERE relkind IN ('r', 'p')), false),
        'SELECT,INSERT,UPDATE,DELETE on every table', 'checked'),
    (12, 'no_public_privileges_on_application_tables_or_sequences', true,
        NOT EXISTS (SELECT 1 FROM public_grants), '0', (SELECT count(*)::text FROM public_grants)),
    (13, 'public_cannot_create_in_schema_public', true,
        NOT has_schema_privilege('public', 'public', 'CREATE'), 'false', has_schema_privilege('public', 'public', 'CREATE')::text),
    (14, 'other_grantees_on_application_relations', false, true, 'owner and application role only',
        coalesce((SELECT names FROM other_grantees), '<none>')),
    (15, 'supabase_data_api_roles_present_in_this_database', false, true, 'informational only',
        (SELECT count(*)::text FROM supabase_roles) || ' of 3 (this check does not establish Data API parity)'),
    (16, 'server_version', false, true, '-', split_part(version(), ' on ', 1))
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
