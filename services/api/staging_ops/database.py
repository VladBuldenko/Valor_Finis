"""
Database access for the staging tooling.

What:
    A read-only probe that reports a server's identity, an engine whose every
    physical connection re-verifies that identity, and the seed lock. There is
    no object-removal primitive: the staging reset is disabled (see reset.py).

Why:
    The identity guard compares facts, so facts must come from the server
    that will be mutated. `bound_engine` makes the mutation connection itself
    prove it reached the verified database; a connection that lands anywhere
    else is closed before it can run a statement.
"""

import json
from contextlib import contextmanager
from typing import Callable, Iterator

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


# Holds the staging advisory lock for the whole seed, on a dedicated
# connection bound to the verified identity.
# The services commit between steps, so only a SESSION lock outlives them; it
# vanishes with the connection, so a crashed seed never leaves it behind.
# Parameters:
# - verified: verified target.
# Yields:
# - A callable that raises SEED_LOCK_LOST unless this connection still holds the lock.
# Raises:
# - StagingRefused: LOCK_BUSY when another seed or bootstrap holds it.
@contextmanager
def seed_lock(verified: VerifiedTarget) -> Iterator[Callable[[], None]]:
    engine = bound_engine(verified)
    connection = None

    try:
        try:
            connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            acquired = connection.exec_driver_sql("SELECT pg_try_advisory_lock(%s, %s)" % binding.LOCK_KEYS).scalar()
        except StagingRefused:
            raise
        except Exception:
            raise StagingRefused("PROBE_FAILED", "the seed lock could not be acquired") from None

        if not acquired:
            raise StagingRefused("LOCK_BUSY", "another staging bootstrap or seed is running")

        held_sql = (
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s AND objid = %s AND objsubid = 2 "
            "AND pid = pg_backend_pid() AND granted" % binding.LOCK_KEYS
        )

        def check() -> None:
            try:
                held = connection.exec_driver_sql(held_sql).scalar()
            except Exception:
                raise StagingRefused("SEED_LOCK_LOST", "the seed lock connection failed; stop and inspect the database before any rerun") from None

            if not held:
                raise StagingRefused("SEED_LOCK_LOST", "the seed lock is no longer held; stop and inspect the database before any rerun")

        # The body's own exceptions propagate unchanged through this yield.
        yield check
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        engine.dispose()


# Serializes the verified identity for the Alembic hook (VF_STAGING_BINDING).
def binding_payload(verified: VerifiedTarget, require_empty: bool) -> str:
    return json.dumps({**verified.binding(), "require_empty": require_empty}, sort_keys=True)
