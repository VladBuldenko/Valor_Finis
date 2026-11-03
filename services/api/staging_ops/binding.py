"""
Identity binding SQL shared by the probe, the bound engine and Alembic.

What:
    The catalog queries that read a server's identity and that count schema
    objects in `public`, plus the check Alembic's env.py runs on its own
    migration connection (`verify_migration_binding`).

Why:
    Alembic opens its own connection from DATABASE_URL, so a check done by the
    parent process says nothing about that connection (time-of-check versus
    time-of-use, DNS or proxy changes). The parent passes the verified
    identity in VF_STAGING_BINDING and env.py re-verifies it inside the
    migration transaction before any DDL. This module imports only the
    standard library and SQLAlchemy so env.py can load it.
"""

import json

IDENTITY_SQL = """
SELECT current_database(),
       (SELECT oid::bigint FROM pg_database WHERE datname = current_database()),
       extract(epoch FROM pg_postmaster_start_time())::text,
       pg_is_in_recovery(),
       current_setting('server_version_num')::int
"""

# Relations, types and functions in `public` that no extension owns. A fresh
# Supabase or PostgreSQL database has none; every table, view, sequence, enum
# and function the migrations create is counted.
UNEXPECTED_OBJECTS_SQL = """
SELECT
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','S','f','c')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'))
+ (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typtype IN ('e','d','r','m')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e'))
+ (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'))
"""

ALEMBIC_TABLE_SQL = "SELECT to_regclass('public.alembic_version') IS NOT NULL"
ALEMBIC_REVISIONS_SQL = "SELECT version_num FROM public.alembic_version ORDER BY version_num"
PUBLIC_TABLES_SQL = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relispartition
   AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
 ORDER BY c.relname
"""

# Advisory lock key for staging bootstrap and reset (distinct from the
# production runner's 7165/2).
LOCK_KEYS = (7165, 3)


# Checks the migration connection against the identity the parent verified.
# Called from alembic/env.py inside the migration transaction. It is inactive
# unless VF_STAGING_BINDING is set, so every other Alembic command is
# unchanged. Messages are fixed codes; no connection detail is ever printed.
# Parameters:
# - connection: the SQLAlchemy connection Alembic will migrate through.
# - raw_binding: JSON text from VF_STAGING_BINDING.
# Raises:
# - RuntimeError: malformed binding, another run in progress, a different
#   database/oid/server start, a standby, or (bootstrap) a non-empty database.
def verify_migration_binding(connection, raw_binding: str) -> None:
    try:
        binding = json.loads(raw_binding)
        expected = (binding["database"], int(binding["oid"]), str(binding["postmaster_start"]))
        require_empty = bool(binding["require_empty"])
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("VF_STAGING_BINDING_INVALID") from None

    if not connection.exec_driver_sql("SELECT pg_try_advisory_xact_lock(%s, %s)" % LOCK_KEYS).scalar():
        raise RuntimeError("VF_STAGING_LOCK_BUSY")

    database, oid, started, in_recovery, _ = connection.exec_driver_sql(IDENTITY_SQL).one()

    if (database, int(oid), started) != expected or in_recovery:
        raise RuntimeError("VF_STAGING_BINDING_MISMATCH")

    if require_empty:
        has_alembic = connection.exec_driver_sql(ALEMBIC_TABLE_SQL).scalar()

        if has_alembic or connection.exec_driver_sql(UNEXPECTED_OBJECTS_SQL).scalar():
            raise RuntimeError("VF_STAGING_NOT_EMPTY")
