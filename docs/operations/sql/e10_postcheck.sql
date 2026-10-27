-- VF-020E10 (migration c4d8a2f6e193) READ-ONLY post-migration verification.
--
-- Run it ONLY through run_readonly_check.sh. Required psql variables: expected_db,
-- app_role (the role the API and the dispatcher connect as), data_api_roles
-- (comma separated), require_roles ('yes' on Supabase: the Data API roles must exist,
-- otherwise the privilege checks would be vacuous).
--
-- READ ONLY, rolled back, bounded timeouts, catalog metadata only (the single row
-- count is a count, never row content). Output: one row per check (OK / FAIL / INFO)
-- and a final CLASSIFICATION row. INFO rows never gate.
--
-- Constraint definitions are compared with parentheses and whitespace removed, so the
-- check does not depend on how a PostgreSQL version parenthesizes them.
--
-- Privilege checks use the has_*_privilege functions, which resolve EFFECTIVE access
-- (role membership with INHERIT, PUBLIC, ownership, column-level grants and
-- superuser), plus an explicit PUBLIC check on the ACLs. Absence of a direct GRANT
-- is NOT accepted as absence of access.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
roles AS (
    SELECT rolname, rolsuper FROM pg_roles
    WHERE rolname = ANY (string_to_array(:'data_api_roles', ','))
),
tbl AS (SELECT to_regclass('public.alert_dispatch_progress') AS oid),
seq AS (SELECT to_regclass('public.alert_dispatch_service_seq') AS oid),
cols AS (
    SELECT string_agg(
               a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':'
               || CASE WHEN a.attnotnull THEN 'NOT NULL' ELSE 'NULL' END || ':'
               || coalesce(pg_get_expr(d.adbin, d.adrelid), ''),
               '|' ORDER BY a.attnum) AS spec,
           count(*) AS n
    FROM pg_attribute a
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid = (SELECT oid FROM tbl) AND a.attnum > 0 AND NOT a.attisdropped
),
cons AS (
    SELECT string_agg(conname || ':' || contype::text || ':' || convalidated::text || ':'
                      || regexp_replace(pg_get_constraintdef(oid), '[()[:space:]]', '', 'g'),
                      '|' ORDER BY conname) AS spec,
           count(*) AS n
    FROM pg_constraint
    WHERE conrelid = (SELECT oid FROM tbl) AND contype IN ('p', 'u', 'c', 'f', 'x')
),
idx AS (
    SELECT string_agg(i.indexname || ':' || split_part(i.indexdef, ' USING ', 2) || ':' || x.indisvalid::text
                      || ':' || x.indisready::text, '|' ORDER BY i.indexname) AS spec,
           count(*) AS n
    FROM pg_indexes i
    JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = 'public'::regnamespace
    JOIN pg_index x ON x.indexrelid = c.oid
    WHERE i.schemaname = 'public' AND i.tablename = 'alert_dispatch_progress'
),
seqinfo AS (
    SELECT data_type::text || ':' || start_value || ':' || min_value || ':' || max_value || ':'
           || increment_by || ':' || cycle::text || ':' || cache_size AS spec,
           last_value
    FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'alert_dispatch_service_seq'
),
-- Every (role, privilege) pair a Data API role holds EFFECTIVELY, on the table, its
-- columns or the sequence.
role_access AS (
    SELECT r.rolname, 'table ' || p AS privilege
    FROM roles r, unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p
    WHERE (SELECT oid FROM tbl) IS NOT NULL AND has_table_privilege(r.rolname, (SELECT oid FROM tbl), p)
    UNION ALL
    SELECT r.rolname, 'column ' || p
    FROM roles r, unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p
    WHERE (SELECT oid FROM tbl) IS NOT NULL AND has_any_column_privilege(r.rolname, (SELECT oid FROM tbl), p)
    UNION ALL
    SELECT r.rolname, 'sequence ' || p
    FROM roles r, unnest(ARRAY['USAGE','SELECT','UPDATE']) p
    WHERE (SELECT oid FROM seq) IS NOT NULL AND has_sequence_privilege(r.rolname, (SELECT oid FROM seq), p)
    UNION ALL
    -- Privilege-list independent: ANY ACL entry (whatever its privilege type, including types a
    -- newer PostgreSQL adds, such as MAINTAIN in 17) held by the Data API role itself or by a
    -- role it is a member of, with or without INHERIT.
    SELECT r.rolname, 'acl ' || c.relname || ' ' || a.privilege_type
    FROM roles r, pg_class c,
         aclexplode(coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) a
    WHERE c.oid IN ((SELECT oid FROM tbl), (SELECT oid FROM seq)) AND a.grantee <> 0
      AND pg_has_role(r.rolname, a.grantee, 'MEMBER')
    UNION ALL
    SELECT r.rolname, 'superuser' FROM roles r WHERE r.rolsuper
),
-- Grantee 0 in an ACL is PUBLIC. A NULL relacl means the default ACL (owner only).
public_access AS (
    SELECT c.relname, a.privilege_type
    FROM pg_class c, aclexplode(coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) a
    WHERE c.oid IN ((SELECT oid FROM tbl), (SELECT oid FROM seq)) AND a.grantee = 0
),
grantees AS (
    SELECT string_agg(DISTINCT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END, ',') AS names
    FROM pg_class c, aclexplode(coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) a
    WHERE c.oid IN ((SELECT oid FROM tbl), (SELECT oid FROM seq))
),
checks(ord, check_name, gating, ok, expected, actual) AS (
    VALUES
    (1, 'transaction_read_only', true,
        current_setting('transaction_read_only') = 'on', 'on', current_setting('transaction_read_only')),
    (2, 'database_name', true,
        current_database() = :'expected_db', :'expected_db', current_database()),
    (3, 'alembic_version_rows', true,
        (SELECT count(*) FROM alembic_version) = 1, '1', (SELECT count(*)::text FROM alembic_version)),
    (4, 'alembic_revision_is_e10', true,
        (SELECT min(version_num) FROM alembic_version) = 'c4d8a2f6e193', 'c4d8a2f6e193',
        coalesce((SELECT min(version_num) FROM alembic_version), '<none>')),
    (5, 'progress_table_exists_regular_permanent', true,
        (SELECT count(*) FROM pg_class WHERE oid = (SELECT oid FROM tbl) AND relkind = 'r' AND relpersistence = 'p') = 1,
        'ordinary permanent table', coalesce((SELECT relkind::text || relpersistence::text FROM pg_class WHERE oid = (SELECT oid FROM tbl)), '<missing>')),
    (6, 'service_sequence_exists', true,
        (SELECT count(*) FROM pg_class WHERE oid = (SELECT oid FROM seq) AND relkind = 'S') = 1,
        'sequence', coalesce((SELECT relkind::text FROM pg_class WHERE oid = (SELECT oid FROM seq)), '<missing>')),
    (7, 'exactly_six_columns_with_types_nullability_defaults', true,
        (SELECT n FROM cols) = 6 AND (SELECT spec FROM cols) =
        'user_id:uuid:NOT NULL:|service_seq:bigint:NOT NULL:|last_attempted_at:timestamp with time zone:NOT NULL:now()'
        '|last_success_at:timestamp with time zone:NULL:|consecutive_failures:integer:NOT NULL:0|last_error_code:character varying(64):NULL:',
        '6 columns as migrated', coalesce((SELECT spec FROM cols), '<none>')),
    (8, 'constraints_pk_unique_two_checks_no_foreign_keys', true,
        (SELECT n FROM cons) = 4 AND (SELECT spec FROM cons) =
        'alert_dispatch_progress_pkey:p:true:PRIMARYKEYuser_id'
        '|ck_alert_dispatch_progress_consecutive_failures_valid:c:true:CHECKconsecutive_failures>=0'
        '|ck_alert_dispatch_progress_last_success_at_valid:c:true:CHECKlast_success_atISNULLORlast_success_at<=last_attempted_at'
        '|uq_alert_dispatch_progress_service_seq:u:true:UNIQUEservice_seq',
        '4 validated constraints', coalesce((SELECT spec FROM cons), '<none>')),
    (9, 'indexes_pk_unique_and_monitoring_all_valid', true,
        (SELECT n FROM idx) = 3 AND (SELECT spec FROM idx) =
        'alert_dispatch_progress_pkey:btree (user_id):true:true'
        '|ix_alert_dispatch_progress_last_success_at:btree (last_success_at):true:true'
        '|uq_alert_dispatch_progress_service_seq:btree (service_seq):true:true',
        '3 valid btree indexes', coalesce((SELECT spec FROM idx), '<none>')),
    (10, 'sequence_properties', true,
        (SELECT spec FROM seqinfo) = 'bigint:1:1:9223372036854775807:1:false:1',
        'bigint:start1:min1:max9223372036854775807:inc1:nocycle:cache1', coalesce((SELECT spec FROM seqinfo), '<missing>')),
    (11, 'table_and_sequence_have_the_same_owner', true,
        (SELECT relowner FROM pg_class WHERE oid = (SELECT oid FROM tbl)) =
        (SELECT relowner FROM pg_class WHERE oid = (SELECT oid FROM seq)),
        'same owner', coalesce((SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = (SELECT oid FROM tbl)), '<missing>')),
    (12, 'owner_is_not_a_data_api_role', true,
        NOT EXISTS (SELECT 1 FROM pg_class c JOIN roles r ON r.rolname = pg_get_userbyid(c.relowner)
                    WHERE c.oid IN ((SELECT oid FROM tbl), (SELECT oid FROM seq))),
        'false', EXISTS (SELECT 1 FROM pg_class c JOIN roles r ON r.rolname = pg_get_userbyid(c.relowner)
                    WHERE c.oid IN ((SELECT oid FROM tbl), (SELECT oid FROM seq)))::text),
    (13, 'application_role_exists', true,
        EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role'), 'true',
        EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')::text),
    (14, 'application_role_can_read_write_table', true,
        coalesce(has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'SELECT')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'INSERT')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'UPDATE')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'DELETE'), false),
        'SELECT,INSERT,UPDATE,DELETE', 'checked'),
    (15, 'application_role_can_call_nextval', true,
        coalesce(has_sequence_privilege(:'app_role', (SELECT oid FROM seq), 'USAGE'), false), 'USAGE', 'checked'),
    (16, 'data_api_roles_resolved', :'require_roles' = 'yes',
        (SELECT count(*) FROM roles) = cardinality(string_to_array(:'data_api_roles', ',')),
        cardinality(string_to_array(:'data_api_roles', ','))::text, (SELECT count(*)::text FROM roles)),
    (17, 'no_effective_data_api_access', true,
        NOT EXISTS (SELECT 1 FROM role_access), '0',
        (SELECT count(*)::text FROM role_access)),
    (18, 'no_public_access_on_table_or_sequence', true,
        NOT EXISTS (SELECT 1 FROM public_access), '0', (SELECT count(*)::text FROM public_access)),
    (19, 'row_level_security_state', false, true, '-',
        coalesce((SELECT relrowsecurity::text FROM pg_class WHERE oid = (SELECT oid FROM tbl)), '<missing>')),
    (20, 'acl_grantees_names_only', false, true, '-', coalesce((SELECT names FROM grantees), '<none>')),
    (21, 'progress_row_count_and_sequence_last_value', false, true, '0 right after migration',
        CASE WHEN (SELECT oid FROM tbl) IS NULL THEN '<missing>'
             ELSE (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM public.alert_dispatch_progress', false, true, '')))[1]::text END
        || ' / ' || coalesce((SELECT last_value::text FROM seqinfo), 'unused')),
    (22, 'ungranted_locks', true,
        (SELECT count(*) FROM pg_locks WHERE NOT granted) = 0, '0',
        (SELECT count(*)::text FROM pg_locks WHERE NOT granted)),
    (23, 'server_version', false, true, '-', split_part(version(), ' on ', 1))
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
