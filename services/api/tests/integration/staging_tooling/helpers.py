"""Builders for the local-cluster staging tests (all values synthetic, loopback only)."""

import contextlib
import copy
import os
from typing import Dict, Tuple

from staging_ops import database
from staging_ops.identity import verify_configuration, verify_facts
from staging_ops.operations import Operations, real_operations
from staging_ops.target_config import parse_approved_targets

STAGING_REF = "stgprojectrefabcdefgh"
PRODUCTION_REF = "prdprojectrefabcdefgh"


def approved_for(cluster, database: str, oid: int):
    return parse_approved_targets(
        {
            "schema_version": 1,
            "staging": [
                {
                    "id": "STG-1",
                    "database": {"host": cluster.host, "port": cluster.port, "name": database, "oid": oid},
                    "supabase_project_ref": STAGING_REF,
                    "approved_by": "Owner",
                    "approved_on": "2026-11-20",
                }
            ],
            "production_denylist": {
                "database_hosts": ["prod-db.example.test"],
                "supabase_project_refs": [PRODUCTION_REF],
                "database_names": ["valor"],
                "recorded_by": "Owner",
                "recorded_on": "2026-11-19",
            },
        }
    )


def environ_for(cluster, database: str) -> Dict[str, str]:
    return {
        "DATABASE_URL": cluster.url(database),
        "SUPABASE_URL": f"https://{STAGING_REF}.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_" + "publishable_" + "FIXTURE" + "KEY0001",
        "AUTH_MODE": "supabase",
        "PATH": os.environ.get("PATH", "/usr/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }


class SpyOperations:
    """Real operations except the Supabase probe (no network) with call counters."""

    def __init__(self) -> None:
        self.real = real_operations()
        self.alembic_runs = 0
        self.supabase_probes = 0

    def _supabase(self, configured, environ) -> None:
        self.supabase_probes += 1

    def _alembic(self, arguments, environment):
        self.alembic_runs += 1

        return self.real.run_alembic(arguments, environment)

    def operations(self) -> Operations:
        return Operations(
            probe=self.real.probe,
            supabase_probe=self._supabase,
            run_alembic=self._alembic,
            repository_heads=self.real.repository_heads,
            expected_tables=self.real.expected_tables,
            open_session=self.real.open_session,
            seed_lock=self.real.seed_lock,
        )


def snapshot(cluster, database: str) -> Tuple[tuple, tuple]:
    """(public relations, alembic revisions) as the catalog sees them now."""

    with contextlib.closing(cluster.connect(database)) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' ORDER BY 1")
        relations = tuple(row[0] for row in cursor.fetchall())
        cursor.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        revisions = ()

        if cursor.fetchone()[0]:
            cursor.execute("SELECT version_num FROM public.alembic_version")
            revisions = tuple(row[0] for row in cursor.fetchall())

    return relations, revisions


def copy_document(document: dict) -> dict:
    return copy.deepcopy(document)


def verified_target(cluster, name: str, oid: int):
    """(environ, VerifiedTarget) for a database that passed the full identity guard."""

    environ = environ_for(cluster, name)
    configured = verify_configuration("staging", "STG-1", environ, approved_for(cluster, name, oid))

    return environ, verify_facts(configured, database.probe_database(configured))


def execute(cluster, name: str, *statements: str) -> None:
    """Runs DDL/DML as the cluster superuser (autocommit); test setup only."""

    with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def fetch(cluster, name: str, sql: str) -> list:
    with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
        cursor.execute(sql)

        return cursor.fetchall()
