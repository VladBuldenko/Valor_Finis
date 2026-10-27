-- VF-020E10 (migration c4d8a2f6e193) READ-ONLY production preflight.
--
-- Run it ONLY through run_readonly_check.sh, and only after the separate written
-- authorization for this gate. Required psql variables: expected_db, app_role,
-- data_api_roles, require_roles (the wrapper supplies them).
--
-- Guarantees: the transaction is READ ONLY and is rolled back; no row content is
-- selected (catalog metadata only); every timeout is bounded. A failing statement
-- aborts the run (ON_ERROR_STOP), which the wrapper reports as STOP.
--
-- Output: one row per check (status OK / FAIL / INFO) and a final CLASSIFICATION
-- row. INFO rows never gate. PASS requires every gating row to be OK.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

WITH
activity AS (
    SELECT * FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
),
checks(ord, check_name, gating, ok, expected, actual) AS (
    VALUES
    (1, 'transaction_read_only', true,
        current_setting('transaction_read_only') = 'on', 'on', current_setting('transaction_read_only')),
    (2, 'database_name', true,
        current_database() = :'expected_db', :'expected_db', current_database()),
    (3, 'server_version_num_ge_150000', true,
        current_setting('server_version_num')::int >= 150000, '>= 150000', current_setting('server_version_num')),
    (4, 'alembic_version_rows', true,
        (SELECT count(*) FROM alembic_version) = 1, '1', (SELECT count(*)::text FROM alembic_version)),
    (5, 'alembic_revision_is_e9a', true,
        (SELECT min(version_num) FROM alembic_version) = 'a7c3e91d5b24', 'a7c3e91d5b24',
        coalesce((SELECT min(version_num) FROM alembic_version), '<none>')),
    (6, 'rule_alerts_exists', true,
        to_regclass('public.rule_alerts') IS NOT NULL, 'true', (to_regclass('public.rule_alerts') IS NOT NULL)::text),
    (7, 'rule_alerts_has_alert_key_constraint', true,
        EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass('public.rule_alerts')
                AND conname = 'uq_rule_alerts_alert_key'), 'true',
        EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass('public.rule_alerts')
                AND conname = 'uq_rule_alerts_alert_key')::text),
    (8, 'progress_table_absent', true,
        to_regclass('public.alert_dispatch_progress') IS NULL, 'true',
        (to_regclass('public.alert_dispatch_progress') IS NULL)::text),
    (9, 'progress_sequence_absent', true,
        to_regclass('public.alert_dispatch_service_seq') IS NULL, 'true',
        (to_regclass('public.alert_dispatch_service_seq') IS NULL)::text),
    (10, 'no_partial_relations_any_schema', true,
        (SELECT count(*) FROM pg_class WHERE relname LIKE 'alert_dispatch%'
            OR relname LIKE '%alert_dispatch_progress%') = 0, '0',
        (SELECT count(*)::text FROM pg_class WHERE relname LIKE 'alert_dispatch%'
            OR relname LIKE '%alert_dispatch_progress%')),
    (11, 'no_partial_constraints_or_types', true,
        (SELECT count(*) FROM pg_constraint WHERE conname LIKE '%alert_dispatch%') = 0
        AND (SELECT count(*) FROM pg_type WHERE typname LIKE '%alert_dispatch%') = 0, '0',
        ((SELECT count(*) FROM pg_constraint WHERE conname LIKE '%alert_dispatch%')
         + (SELECT count(*) FROM pg_type WHERE typname LIKE '%alert_dispatch%'))::text),
    (12, 'can_create_in_public_schema', true,
        has_schema_privilege(current_user, 'public', 'CREATE'), 'true',
        has_schema_privilege(current_user, 'public', 'CREATE')::text),
    (13, 'sessions_idle_in_transaction', true,
        (SELECT count(*) FROM activity WHERE state LIKE 'idle in transaction%') = 0, '0',
        (SELECT count(*)::text FROM activity WHERE state LIKE 'idle in transaction%')),
    (14, 'transactions_older_than_5_minutes', true,
        (SELECT count(*) FROM activity WHERE xact_start < now() - interval '5 minutes') = 0, '0',
        (SELECT count(*)::text FROM activity WHERE xact_start < now() - interval '5 minutes')),
    (15, 'prepared_transactions', true,
        (SELECT count(*) FROM pg_prepared_xacts WHERE database = current_database()) = 0, '0',
        (SELECT count(*)::text FROM pg_prepared_xacts WHERE database = current_database())),
    (16, 'ungranted_locks', true,
        (SELECT count(*) FROM pg_locks WHERE NOT granted) = 0, '0',
        (SELECT count(*)::text FROM pg_locks WHERE NOT granted)),
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
    (20, 'connected_role', false, true, '-', current_user::text)
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
