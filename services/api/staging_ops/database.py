"""
Database access for the staging tooling.

What:
    A read-only probe that reports a server's identity, an engine whose every
    physical connection re-verifies that identity, and the reset primitives
    (data description and object removal).

Why:
    The identity guard compares facts, so facts must come from the server
    that will be mutated. `bound_engine` makes the mutation connection itself
    prove it reached the verified database; a connection that lands anywhere
    else is closed before it can run a statement.
"""

import json
from typing import List, Tuple

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from staging_ops import binding
from staging_ops.errors import StagingRefused
from staging_ops.identity import ConfiguredTarget, DatabaseFacts, VerifiedTarget

CONNECT_TIMEOUT_SECONDS = 10
PROBE_OPTIONS = "-c lock_timeout=5000 -c statement_timeout=60000 -c default_transaction_read_only=on"
MUTATION_OPTIONS = "-c lock_timeout=5000 -c statement_timeout=120000"


def _engine(configured: ConfiguredTarget, options: str) -> Engine:
    return create_engine(
        configured.database_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS, "options": options},
    )


# Reads the identity and schema facts of the server behind a URL, read-only.
# The probe session is read-only at the server, so even a bug here cannot write.
# Parameters:
# - configured: target that passed verify_configuration.
# Returns:
# - DatabaseFacts.
# Raises:
# - StagingRefused: PROBE_FAILED when the server cannot be queried.
def probe_database(configured: ConfiguredTarget) -> DatabaseFacts:
    engine = _engine(configured, PROBE_OPTIONS)

    try:
        with engine.connect() as connection:
            database, oid, started, in_recovery, version = connection.exec_driver_sql(binding.IDENTITY_SQL).one()
            unexpected = connection.exec_driver_sql(binding.UNEXPECTED_OBJECTS_SQL).scalar()
            has_alembic = connection.exec_driver_sql(binding.ALEMBIC_TABLE_SQL).scalar()
            revisions = None

            if has_alembic:
                revisions = tuple(row[0] for row in connection.exec_driver_sql(binding.ALEMBIC_REVISIONS_SQL))

            tables = tuple(row[0] for row in connection.exec_driver_sql(binding.PUBLIC_TABLES_SQL))
    except Exception:
        # Driver messages can carry connection details; report a fixed text.
        raise StagingRefused("PROBE_FAILED", "the database could not be queried") from None
    finally:
        engine.dispose()

    return DatabaseFacts(
        database=database,
        oid=int(oid),
        postmaster_start=started,
        in_recovery=bool(in_recovery),
        server_version_num=int(version),
        unexpected_objects=int(unexpected),
        alembic_revisions=revisions,
        public_tables=tables,
    )


# Builds an engine whose every new physical connection re-verifies the
# identity first. The connection is closed before any statement runs if the
# database name, oid or server start differs from the verified target.
# Parameters:
# - verified: identity captured by verify_facts.
# Returns:
# - SQLAlchemy Engine (no pooling: each checkout is a freshly verified connection).
def bound_engine(verified: VerifiedTarget) -> Engine:
    engine = _engine(verified.configured, MUTATION_OPTIONS)

    @event.listens_for(engine, "connect")
    def _verify_connection(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()

        try:
            cursor.execute(binding.IDENTITY_SQL)
            database, oid, started, in_recovery, _version = cursor.fetchone()
        finally:
            cursor.close()

        dbapi_connection.rollback()

        if (database, int(oid), started) != (verified.configured.database, verified.oid, verified.postmaster_start) or in_recovery:
            dbapi_connection.close()
            raise StagingRefused("CONNECTION_IDENTITY_CHANGED", "a new connection reached a different database than the verified target")

    return engine


# Describes what a reset would destroy: exact row counts per table plus the
# number of other schema objects. Read-only.
# Parameters:
# - verified: verified target.
# Returns:
# - (list of (table, row_count), count of non-table objects).
def describe_data(verified: VerifiedTarget) -> Tuple[List[Tuple[str, int]], int]:
    engine = _engine(verified.configured, PROBE_OPTIONS)

    try:
        with engine.connect() as connection:
            names = [row[0] for row in connection.exec_driver_sql(binding.PUBLIC_TABLES_SQL)]
            counts = []

            for name in names:
                quoted = f"public.{connection.dialect.identifier_preparer.quote(name)}"
                counts.append((name, int(connection.exec_driver_sql(f"SELECT count(*) FROM {quoted}").scalar())))

            unexpected = int(connection.exec_driver_sql(binding.UNEXPECTED_OBJECTS_SQL).scalar())
    except Exception:
        raise StagingRefused("PROBE_FAILED", "the database could not be queried") from None
    finally:
        engine.dispose()

    return counts, max(unexpected - len(counts), 0)


_DROP_STATEMENTS_SQL = """
SELECT stmt FROM (
  SELECT 1 AS ord, format('DROP VIEW IF EXISTS %I.%I CASCADE', n.nspname, c.relname) AS stmt
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'v' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
  UNION ALL
  SELECT 2, format('DROP MATERIALIZED VIEW IF EXISTS %I.%I CASCADE', n.nspname, c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'm' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
  UNION ALL
  SELECT 3, format('DROP FOREIGN TABLE IF EXISTS %I.%I CASCADE', n.nspname, c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'f' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
  UNION ALL
  SELECT 4, format('DROP TABLE IF EXISTS %I.%I CASCADE', n.nspname, c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relispartition AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
  UNION ALL
  SELECT 5, format('DROP SEQUENCE IF EXISTS %I.%I CASCADE', n.nspname, c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'S' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
  UNION ALL
  SELECT 6, format('DROP %s IF EXISTS %I.%I(%s) CASCADE',
                   CASE p.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END,
                   n.nspname, p.proname, pg_get_function_identity_arguments(p.oid))
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
  UNION ALL
  SELECT 7, format('DROP TYPE IF EXISTS %I.%I CASCADE', n.nspname, t.typname)
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
   WHERE n.nspname = 'public' AND t.typtype IN ('e','d','r','m') AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e')
) statements ORDER BY ord, stmt
"""


# Removes every application object from `public` in ONE transaction.
# The connection is bound to the verified identity (bound_engine), takes the
# staging advisory lock, drops views, tables, sequences, functions and types
# that no extension owns, and commits only when nothing unexpected remains.
# Supabase-managed schemas (auth, storage, ...) and roles are never touched.
# Parameters:
# - verified: verified target.
# Returns:
# - Number of statements executed.
# Raises:
# - StagingRefused: LOCK_BUSY, RESET_INCOMPLETE; the transaction rolls back.
def destroy_application_objects(verified: VerifiedTarget) -> int:
    engine = bound_engine(verified)

    try:
        with engine.begin() as connection:
            if not connection.exec_driver_sql("SELECT pg_try_advisory_xact_lock(%s, %s)" % binding.LOCK_KEYS).scalar():
                raise StagingRefused("LOCK_BUSY", "another staging bootstrap or reset is running")

            statements = [row[0] for row in connection.execute(text(_DROP_STATEMENTS_SQL))]

            for statement in statements:
                connection.exec_driver_sql(statement)

            if connection.exec_driver_sql(binding.UNEXPECTED_OBJECTS_SQL).scalar():
                raise StagingRefused("RESET_INCOMPLETE", "schema objects remain after the reset; nothing was committed")
    except StagingRefused:
        raise
    except Exception:
        raise StagingRefused("RESET_FAILED", "the reset failed and was rolled back") from None
    finally:
        engine.dispose()

    return len(statements)


# Serializes the verified identity for the Alembic hook (VF_STAGING_BINDING).
def binding_payload(verified: VerifiedTarget, require_empty: bool) -> str:
    return json.dumps({**verified.binding(), "require_empty": require_empty}, sort_keys=True)
