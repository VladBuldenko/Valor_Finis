-- VF-020E9A (migration a7c3e91d5b24) READ-ONLY post-migration verification.
--
-- Run it ONLY through run_readonly_check.sh, right after the E9A migration (Gate D),
-- while the database is still AT a7c3e91d5b24. After the E10 migration use
-- e10_postcheck.sql instead (its revision check is c4d8a2f6e193). Required psql
-- variables: expected_db, app_role, data_api_roles, require_roles.
--
-- READ ONLY, rolled back, bounded timeouts, catalog metadata and counts only.
-- Output: one row per check (OK / FAIL / INFO) and a final CLASSIFICATION row.
--
-- Definitions are compared with parentheses and whitespace removed, so the check does
-- not depend on how a PostgreSQL version parenthesizes them. Privilege checks use the
-- has_*_privilege functions, which resolve EFFECTIVE access (role membership with
-- INHERIT, PUBLIC, ownership, column-level grants, superuser), plus an explicit PUBLIC
-- check on the ACL. Absence of a direct GRANT is NOT accepted as absence of access.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
roles AS (
    SELECT rolname, rolsuper FROM pg_roles
    WHERE rolname = ANY (string_to_array(:'data_api_roles', ','))
),
tbl AS (SELECT to_regclass('public.rule_alerts') AS oid),
seq AS (SELECT NULL::regclass AS oid),
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
    SELECT string_agg(i.indexname || ':' || regexp_replace(split_part(i.indexdef, ' USING ', 2), '[()[:space:]]', '', 'g')
                      || ':' || x.indisvalid::text || ':' || x.indisready::text, '|' ORDER BY i.indexname) AS spec,
           count(*) AS n
    FROM pg_indexes i
    JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = 'public'::regnamespace
    JOIN pg_index x ON x.indexrelid = c.oid
    WHERE i.schemaname = 'public' AND i.tablename = 'rule_alerts'
),
fk AS (
    SELECT confdeltype::text AS action,
           (SELECT string_agg(attname::text, ',') FROM pg_attribute
             WHERE attrelid = conrelid AND attnum = ANY (confdelsetcols)) AS nulled_columns
    FROM pg_constraint WHERE conrelid = (SELECT oid FROM tbl) AND contype = 'f'
),
-- Every (role, privilege) pair a Data API role holds EFFECTIVELY, on the table or its
-- columns (E9A creates no sequence).
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
    (4, 'alembic_revision_is_e9a', true,
        (SELECT min(version_num) FROM alembic_version) = 'a7c3e91d5b24', 'a7c3e91d5b24',
        coalesce((SELECT min(version_num) FROM alembic_version), '<none>')),
    (5, 'rule_alerts_exists_regular_permanent', true,
        (SELECT count(*) FROM pg_class WHERE oid = (SELECT oid FROM tbl) AND relkind = 'r' AND relpersistence = 'p') = 1,
        'ordinary permanent table', coalesce((SELECT relkind::text || relpersistence::text FROM pg_class WHERE oid = (SELECT oid FROM tbl)), '<missing>')),
    (6, 'exactly_eleven_columns_with_types_nullability_defaults', true,
        (SELECT n FROM cols) = 11 AND (SELECT spec FROM cols) =
        'id:uuid:NOT NULL:|user_id:uuid:NOT NULL:|rule_id:uuid:NULL:|rule_type:character varying(32):NOT NULL:'
        '|subject_type:character varying(16):NOT NULL:|subject_id:uuid:NOT NULL:|period_key:character varying(40):NOT NULL:'
        '|level:character varying(16):NOT NULL:|created_at:timestamp with time zone:NOT NULL:now()'
        '|acknowledged_at:timestamp with time zone:NULL:|resolved_at:timestamp with time zone:NULL:',
        '11 columns as migrated', coalesce((SELECT spec FROM cols), '<none>')),
    (7, 'constraints_pk_fk_unique_and_six_checks_all_validated', true,
        (SELECT n FROM cons) = 9 AND (SELECT spec FROM cons) =
        'ck_rule_alerts_acknowledged_at_valid:c:true:CHECKacknowledged_atISNULLORacknowledged_at>=created_at'
        '|ck_rule_alerts_level_valid:c:true:CHECKlevel::text=ANYARRAY[''watch''::charactervarying,''at_risk''::charactervarying,''exceeded''::charactervarying,''breached''::charactervarying]::text[]'
        '|ck_rule_alerts_resolved_at_valid:c:true:CHECKresolved_atISNULLORresolved_at>=created_at'
        '|ck_rule_alerts_rule_type_valid:c:true:CHECKrule_type::text=ANYARRAY[''MINIMUM_UNALLOCATED_FLOOR''::charactervarying,''OVERCOMMITMENT_ALERT''::charactervarying,''BUDGET_ALERT''::charactervarying]::text[]'
        '|ck_rule_alerts_subject_type_valid:c:true:CHECKsubject_type::text=ANYARRAY[''account''::charactervarying,''budget''::charactervarying]::text[]'
        '|ck_rule_alerts_type_shape:c:true:CHECKrule_type::text=''BUDGET_ALERT''::textANDsubject_type::text=''budget''::textANDlevel::text=ANYARRAY[''watch''::charactervarying,''at_risk''::charactervarying,''exceeded''::charactervarying]::text[]ANDperiod_key::text~''^[0-9]{4}-[0-9]{2}-[0-9]{2}$''::textANDresolved_atISNULLORrule_type::text=ANYARRAY[''MINIMUM_UNALLOCATED_FLOOR''::charactervarying,''OVERCOMMITMENT_ALERT''::charactervarying]::text[]ANDsubject_type::text=''account''::textANDlevel::text=''breached''::textANDperiod_key::text~''^E[1-9][0-9]{0,8}$''::text'
        '|fk_rule_alerts_rule_id_user_id:f:true:FOREIGNKEYrule_id,user_idREFERENCESfinancial_rulesid,user_idONDELETESETNULLrule_id'
        '|rule_alerts_pkey:p:true:PRIMARYKEYid'
        '|uq_rule_alerts_alert_key:u:true:UNIQUEuser_id,rule_type,subject_id,period_key,level',
        '9 validated constraints', coalesce((SELECT spec FROM cons), '<none>')),
    (8, 'foreign_key_nulls_only_rule_id_on_rule_delete', true,
        (SELECT action FROM fk) = 'n' AND (SELECT nulled_columns FROM fk) = 'rule_id', 'n / rule_id',
        coalesce((SELECT action || ' / ' || coalesce(nulled_columns, '<all columns>') FROM fk), '<missing>')),
    (9, 'five_valid_indexes_with_partial_predicates', true,
        (SELECT n FROM idx) = 5 AND (SELECT spec FROM idx) =
        'ix_rule_alerts_rule_id:btreerule_idWHERErule_idISNOTNULL:true:true'
        '|ix_rule_alerts_user_id_unacknowledged:btreeuser_id,created_at,idWHEREacknowledged_atISNULL:true:true'
        '|rule_alerts_pkey:btreeid:true:true'
        '|uq_rule_alerts_alert_key:btreeuser_id,rule_type,subject_id,period_key,level:true:true'
        '|uq_rule_alerts_open_account_episode:btreeuser_id,rule_type,subject_idWHEREresolved_atISNULLANDrule_type::text<>''BUDGET_ALERT''::text:true:true',
        '5 valid indexes', coalesce((SELECT spec FROM idx), '<none>')),
    (10, 'no_rule_alert_sequence', true,
        (SELECT count(*) FROM pg_class WHERE relkind = 'S' AND relname LIKE '%rule_alert%') = 0, '0',
        (SELECT count(*)::text FROM pg_class WHERE relkind = 'S' AND relname LIKE '%rule_alert%')),
    (11, 'owner_is_not_a_data_api_role', true,
        NOT EXISTS (SELECT 1 FROM pg_class c JOIN roles r ON r.rolname = pg_get_userbyid(c.relowner)
                    WHERE c.oid = (SELECT oid FROM tbl)),
        'false', EXISTS (SELECT 1 FROM pg_class c JOIN roles r ON r.rolname = pg_get_userbyid(c.relowner)
                    WHERE c.oid = (SELECT oid FROM tbl))::text),
    (12, 'application_role_exists', true,
        EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role'), 'true',
        EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')::text),
    (13, 'application_role_can_read_write_table', true,
        coalesce(has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'SELECT')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'INSERT')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'UPDATE')
             AND has_table_privilege(:'app_role', (SELECT oid FROM tbl), 'DELETE'), false),
        'SELECT,INSERT,UPDATE,DELETE', 'checked'),
    (14, 'data_api_roles_resolved', :'require_roles' = 'yes',
        (SELECT count(*) FROM roles) = cardinality(string_to_array(:'data_api_roles', ',')),
        cardinality(string_to_array(:'data_api_roles', ','))::text, (SELECT count(*)::text FROM roles)),
    (15, 'no_effective_data_api_access', true,
        NOT EXISTS (SELECT 1 FROM role_access), '0', (SELECT count(*)::text FROM role_access)),
    (16, 'no_public_access_on_table', true,
        NOT EXISTS (SELECT 1 FROM public_access), '0', (SELECT count(*)::text FROM public_access)),
    (17, 'row_level_security_state', false, true, '-',
        coalesce((SELECT relrowsecurity::text FROM pg_class WHERE oid = (SELECT oid FROM tbl)), '<missing>')),
    (18, 'acl_grantees_names_only', false, true, '-', coalesce((SELECT names FROM grantees), '<none>')),
    (19, 'ungranted_locks', true,
        (SELECT count(*) FROM pg_locks WHERE NOT granted) = 0, '0',
        (SELECT count(*)::text FROM pg_locks WHERE NOT granted)),
    (20, 'server_version', false, true, '-', split_part(version(), ' on ', 1)),
    -- Alert rows are not expected before the E9B runtime writes them; the counts below
    -- must equal the preflight counts for every pre-existing table.
    (21, 'row_count:rule_alerts', false, true, '0 right after migration',
        CASE WHEN (SELECT oid FROM tbl) IS NULL THEN '<missing>'
             ELSE (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM public.rule_alerts', false, true, '')))[1]::text END)
),
counts(ord, check_name, gating, ok, expected, actual) AS (
    SELECT 100 + row_number() OVER (ORDER BY t), 'row_count:' || t, false, true, 'equals preflight',
           CASE WHEN to_regclass('public.' || t) IS NULL THEN '<missing>'
                ELSE (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', t), false, true, '')))[1]::text END
    FROM unnest(ARRAY['accounts','budgets','financial_events','financial_rules','goal_transactions','goals',
                      'rule_execution_audit','rule_execution_items','rule_executions']) AS t
),
all_checks AS (SELECT * FROM checks UNION ALL SELECT * FROM counts)
SELECT check_name, status, expected, actual FROM (
    SELECT ord, check_name,
           CASE WHEN coalesce(ok, false) THEN 'OK' WHEN gating THEN 'FAIL' ELSE 'INFO' END AS status,
           expected, actual
    FROM all_checks
    UNION ALL
    SELECT 999, 'CLASSIFICATION',
           CASE WHEN bool_and(coalesce(ok, false) OR NOT gating) THEN 'PASS' ELSE 'STOP' END,
           'every gating check OK', count(*) FILTER (WHERE gating AND NOT coalesce(ok, false)) || ' gating failure(s)'
    FROM all_checks
) AS report
ORDER BY ord;

ROLLBACK;
