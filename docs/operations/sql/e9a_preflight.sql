-- VF-020E9A (migration a7c3e91d5b24) READ-ONLY production preflight.
--
-- Run it ONLY through run_readonly_check.sh, and only after the separate written
-- authorization for this gate. Required psql variables: expected_db, app_role,
-- data_api_roles, require_roles (the wrapper supplies them).
--
-- Guarantees: the transaction is READ ONLY and is rolled back; no row content is
-- selected (catalog metadata and COUNTS only); every timeout is bounded. A failing
-- statement aborts the run (ON_ERROR_STOP), which the wrapper reports as STOP.
--
-- The only lock the migration takes on an existing table is SHARE ROW EXCLUSIVE on
-- financial_rules, so this script also looks for sessions that could block it.
--
-- Output: one row per check (OK / FAIL / INFO) and a final CLASSIFICATION row. INFO
-- rows never gate; the row_count rows must be saved and compared with the post-check.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
activity AS (
    SELECT * FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
),
base(ord, check_name, gating, ok, expected, actual) AS (
    VALUES
    (1, 'transaction_read_only', true,
        current_setting('transaction_read_only') = 'on', 'on', current_setting('transaction_read_only')),
    (2, 'database_name', true,
        current_database() = :'expected_db', :'expected_db', current_database()),
    (3, 'server_version_num_ge_150000_for_set_null_column_list', true,
        current_setting('server_version_num')::int >= 150000, '>= 150000', current_setting('server_version_num')),
    (4, 'alembic_version_rows', true,
        (SELECT count(*) FROM alembic_version) = 1, '1', (SELECT count(*)::text FROM alembic_version)),
    (5, 'alembic_revision_is_e6_parent', true,
        (SELECT min(version_num) FROM alembic_version) = 'e0503e9ca9d3', 'e0503e9ca9d3',
        coalesce((SELECT min(version_num) FROM alembic_version), '<none>')),
    (6, 'prerequisite_tables_exist', true,
        (SELECT count(*) FROM unnest(ARRAY['financial_rules','rule_executions','rule_execution_items',
            'rule_execution_audit','financial_events','goal_transactions','accounts','budgets','goals']) t
            WHERE to_regclass('public.' || t) IS NOT NULL) = 9, '9',
        (SELECT count(*)::text FROM unnest(ARRAY['financial_rules','rule_executions','rule_execution_items',
            'rule_execution_audit','financial_events','goal_transactions','accounts','budgets','goals']) t
            WHERE to_regclass('public.' || t) IS NOT NULL)),
    (7, 'financial_rules_unique_id_user_id_exists', true,
        EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass('public.financial_rules')
                AND conname = 'uq_financial_rules_id_user_id' AND contype = 'u'), 'true',
        EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass('public.financial_rules')
                AND conname = 'uq_financial_rules_id_user_id' AND contype = 'u')::text),
    (8, 'rule_alerts_absent', true,
        to_regclass('public.rule_alerts') IS NULL, 'true', (to_regclass('public.rule_alerts') IS NULL)::text),
    (9, 'no_partial_relations_any_schema', true,
        (SELECT count(*) FROM pg_class WHERE relname LIKE '%rule_alert%') = 0, '0',
        (SELECT count(*)::text FROM pg_class WHERE relname LIKE '%rule_alert%')),
    (10, 'no_partial_constraints_or_types', true,
        (SELECT count(*) FROM pg_constraint WHERE conname LIKE '%rule_alerts%') = 0
        AND (SELECT count(*) FROM pg_type WHERE typname LIKE '%rule_alert%') = 0, '0',
        ((SELECT count(*) FROM pg_constraint WHERE conname LIKE '%rule_alerts%')
         + (SELECT count(*) FROM pg_type WHERE typname LIKE '%rule_alert%'))::text),
    (11, 'can_create_in_public_schema', true,
        has_schema_privilege(current_user, 'public', 'CREATE'), 'true',
        has_schema_privilege(current_user, 'public', 'CREATE')::text),
    (12, 'sessions_idle_in_transaction', true,
        (SELECT count(*) FROM activity WHERE state LIKE 'idle in transaction%') = 0, '0',
        (SELECT count(*)::text FROM activity WHERE state LIKE 'idle in transaction%')),
    (13, 'transactions_older_than_5_minutes', true,
        (SELECT count(*) FROM activity WHERE xact_start < now() - interval '5 minutes') = 0, '0',
        (SELECT count(*)::text FROM activity WHERE xact_start < now() - interval '5 minutes')),
    (14, 'prepared_transactions', true,
        (SELECT count(*) FROM pg_prepared_xacts WHERE database = current_database()) = 0, '0',
        (SELECT count(*)::text FROM pg_prepared_xacts WHERE database = current_database())),
    (15, 'ungranted_locks', true,
        (SELECT count(*) FROM pg_locks WHERE NOT granted) = 0, '0',
        (SELECT count(*)::text FROM pg_locks WHERE NOT granted)),
    -- Modes that conflict with SHARE ROW EXCLUSIVE (ROW EXCLUSIVE is what ordinary
    -- writes take and DOES conflict, so a busy table can delay the lock; the
    -- migration's lock_timeout then makes it fail cleanly instead of waiting).
    (16, 'locks_on_financial_rules_that_conflict_with_the_migration', true,
        (SELECT count(*) FROM pg_locks l WHERE l.locktype = 'relation'
            AND l.relation = to_regclass('public.financial_rules') AND l.pid <> pg_backend_pid()
            AND l.mode IN ('RowExclusiveLock','ShareUpdateExclusiveLock','ShareLock','ShareRowExclusiveLock',
                           'ExclusiveLock','AccessExclusiveLock')) = 0, '0',
        (SELECT count(*)::text FROM pg_locks l WHERE l.locktype = 'relation'
            AND l.relation = to_regclass('public.financial_rules') AND l.pid <> pg_backend_pid()
            AND l.mode IN ('RowExclusiveLock','ShareUpdateExclusiveLock','ShareLock','ShareRowExclusiveLock',
                           'ExclusiveLock','AccessExclusiveLock'))),
    -- A role that cannot read all session statistics sees NULL state/xact_start (and a NULL
    -- backend_type) for other users' sessions, so the session rows above would count 0 and be
    -- vacuous. Fail closed unless the runner role can see every session.
    (17, 'runner_can_see_all_sessions', true,
        coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = current_user), false)
            OR pg_has_role(current_user, 'pg_read_all_stats', 'USAGE'),
        'superuser or pg_read_all_stats',
        CASE WHEN coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = current_user), false)
                  OR pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')
             THEN 'yes' ELSE 'no' END),
    (18, 'data_api_roles_present', :'require_roles' = 'yes',
        (SELECT count(*) FROM pg_roles WHERE rolname = ANY (string_to_array(:'data_api_roles', ',')))
            = cardinality(string_to_array(:'data_api_roles', ',')),
        cardinality(string_to_array(:'data_api_roles', ','))::text,
        (SELECT count(*)::text FROM pg_roles WHERE rolname = ANY (string_to_array(:'data_api_roles', ',')))),
    (19, 'server_version', false, true, '-', split_part(version(), ' on ', 1)),
    (20, 'connected_role', false, true, '-', current_user::text),
    (21, 'database_size', false, true, '-', pg_size_pretty(pg_database_size(current_database())))
),
-- COUNTS only (never row content): save this output and compare it with the post-check.
counts(ord, check_name, gating, ok, expected, actual) AS (
    SELECT 100 + row_number() OVER (ORDER BY t), 'row_count:' || t, false, true, '-',
           CASE WHEN to_regclass('public.' || t) IS NULL THEN '<missing>'
                ELSE (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', t), false, true, '')))[1]::text END
    FROM unnest(ARRAY['accounts','budgets','financial_events','financial_rules','goal_transactions','goals',
                      'rule_execution_audit','rule_execution_items','rule_executions']) AS t
),
checks AS (SELECT * FROM base UNION ALL SELECT * FROM counts)
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
