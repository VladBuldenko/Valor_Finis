"""
Shared fixtures for the staging tooling tests.

Every value here is synthetic: hosts end in `.example.test`, the Supabase
project references are made-up strings, and no test contacts a network or a
real database. Secret-looking values are assembled from fragments so a
repository scan never sees a complete token.
"""

import contextlib
import json
import os
from typing import Callable, List, Optional, Sequence

from staging_ops.errors import StagingRefused
from staging_ops.identity import DatabaseFacts
from staging_ops.operations import AlembicResult, Operations
from staging_ops.target_config import ApprovedTargets, parse_approved_targets

STAGING_HOST = "staging-db.example.test"
PRODUCTION_HOST = "prod-db.example.test"
STAGING_REF = "stgprojectrefabcdefgh"
PRODUCTION_REF = "prdprojectrefabcdefgh"
DATABASE = "valor_staging"
OID = 424242
POSTMASTER = "1700000000.5"
HEAD = "c4d8a2f6e193"
PASSWORD = "pw" + "-" + "fixture" + "-" + "7431"
PUBLISHABLE_KEY = "sb_" + "publishable_" + "FIXTURE" + "KEY0001"
MODEL_TABLES = ("accounts", "goals")


def approved_document() -> dict:
    return {
        "schema_version": 1,
        "staging": [
            {
                "id": "STG-1",
                "database": {"host": STAGING_HOST, "port": 5432, "name": DATABASE, "oid": OID},
                "supabase_project_ref": STAGING_REF,
                "approved_by": "Owner",
                "approved_on": "2026-11-20",
            }
        ],
        "production_denylist": {
            "database_hosts": [PRODUCTION_HOST],
            "supabase_project_refs": [PRODUCTION_REF],
            "database_names": ["valor"],
            "recorded_by": "Owner",
            "recorded_on": "2026-11-19",
        },
    }


def approved(mutate: Optional[Callable[[dict], None]] = None) -> ApprovedTargets:
    document = approved_document()

    if mutate:
        mutate(document)

    return parse_approved_targets(document)


def database_url(host: str = STAGING_HOST, port: int = 5432, database: str = DATABASE, user: str = "svc_user", query: str = "sslmode=require") -> str:
    return f"postgresql://{user}:{PASSWORD}@{host}:{port}/{database}" + (f"?{query}" if query else "")


def good_environ(**overrides: Optional[str]) -> dict:
    environ = {
        "DATABASE_URL": database_url(),
        "SUPABASE_URL": f"https://{STAGING_REF}.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": PUBLISHABLE_KEY,
        "AUTH_MODE": "supabase",
        "PATH": "/usr/bin",
        "HOME": "/home/operator",
    }

    for name, value in overrides.items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value

    return environ


def facts(**overrides) -> DatabaseFacts:
    values = dict(
        database=DATABASE,
        oid=OID,
        postmaster_start=POSTMASTER,
        in_recovery=False,
        server_version_num=170002,
        unexpected_objects=0,
        alembic_revisions=None,
        public_tables=(),
    )
    values.update(overrides)

    return DatabaseFacts(**values)


def migrated_facts(**overrides) -> DatabaseFacts:
    return facts(**{**dict(alembic_revisions=(HEAD,), public_tables=tuple(sorted(MODEL_TABLES + ("alembic_version",))), unexpected_objects=4), **overrides})


class FakeOps:
    """Records every capability call; `mutations` counts only state-changing ones."""

    def __init__(
        self,
        probes: Optional[Sequence[DatabaseFacts]] = None,
        heads: Sequence[str] = (HEAD,),
        alembic_returncode: int = 0,
        alembic_output: str = "",
        supabase_error: Optional[Exception] = None,
        tables: Sequence[str] = MODEL_TABLES,
        lock_busy: bool = False,
    ) -> None:
        self.probes: List[DatabaseFacts] = list(probes) if probes is not None else [facts(), facts(), migrated_facts()]
        self.heads = heads
        self.alembic_returncode = alembic_returncode
        self.alembic_output = alembic_output
        self.supabase_error = supabase_error
        self.tables = tables
        self.lock_busy = lock_busy
        self.lock_checks = 0
        self.lock_entered = 0
        self.lock_released = 0
        self.calls: List[str] = []
        self.alembic_environments: List[dict] = []
        self.alembic_arguments: List[tuple] = []
        self.sessions = 0
        self._probe_index = 0

    @property
    def mutations(self) -> int:
        return len(self.alembic_arguments) + self.sessions

    def _probe(self, configured) -> DatabaseFacts:
        self.calls.append("probe")
        index = min(self._probe_index, len(self.probes) - 1)
        self._probe_index += 1

        return self.probes[index]

    def _supabase(self, configured, environ) -> None:
        self.calls.append("supabase")

        if self.supabase_error:
            raise self.supabase_error

    def _alembic(self, arguments, environment) -> AlembicResult:
        self.calls.append("alembic")
        self.alembic_arguments.append(tuple(arguments))
        self.alembic_environments.append(dict(environment))

        return AlembicResult(self.alembic_returncode, self.alembic_output)

    def _heads(self):
        self.calls.append("heads")

        return self.heads

    def _expected_tables(self):
        return self.tables

    @contextlib.contextmanager
    def _seed_lock(self, verified):
        self.calls.append("seed_lock")

        if self.lock_busy:
            raise StagingRefused("LOCK_BUSY", "another staging bootstrap or seed is running")

        self.lock_entered += 1

        def check():
            self.lock_checks += 1

        try:
            yield check
        finally:
            self.lock_released += 1

    def _open_session(self, verified):
        self.calls.append("open_session")
        self.sessions += 1
        raise AssertionError("the fake must not provide a real session")

    def as_operations(self) -> Operations:
        return Operations(
            probe=self._probe,
            supabase_probe=self._supabase,
            run_alembic=self._alembic,
            repository_heads=self._heads,
            expected_tables=self._expected_tables,
            open_session=self._open_session,
            seed_lock=self._seed_lock,
        )


def write_approved_file(directory, document: Optional[dict] = None, mode: int = 0o600) -> str:
    path = os.path.join(str(directory), "approved-targets.json")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document or approved_document(), handle)

    os.chmod(path, mode)

    return path
