"""
Injectable operations for bootstrap, reset and seed.

What:
    The side-effecting capabilities (probe a database, probe Supabase, run
    Alembic, describe and destroy data, open a session) bundled so tests can
    substitute fakes and assert that a mutation was never invoked.

Why:
    Orchestration code decides WHETHER a mutation may run; these callables
    are the only things that perform one. `real_operations()` wires the real
    implementations and is used by the command line only.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from staging_ops import database
from staging_ops.identity import ConfiguredTarget, DatabaseFacts, VerifiedTarget
from staging_ops.redaction import redact
from staging_ops.supabase_probe import probe_supabase_project

API_DIRECTORY = Path(__file__).resolve().parents[1]
ALEMBIC_TIMEOUT_SECONDS = 900

# Variables the Alembic child process receives. Everything else (including any
# libpq PG* variable) is dropped so the child cannot be redirected.
CHILD_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
CHILD_CONFIGURATION = ("DATABASE_URL", "AUTH_MODE", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")


@dataclass(frozen=True)
class AlembicResult:
    returncode: int
    output: str


@dataclass
class Operations:
    probe: Callable[[ConfiguredTarget], DatabaseFacts]
    supabase_probe: Callable[[ConfiguredTarget, Mapping[str, str]], None]
    run_alembic: Callable[[Sequence[str], Mapping[str, str]], AlembicResult]
    repository_heads: Callable[[], Sequence[str]]
    expected_tables: Callable[[], Iterable[str]]
    describe: Callable[[VerifiedTarget], Tuple[List[Tuple[str, int]], int]]
    destroy: Callable[[VerifiedTarget], int]
    open_session: Optional[Callable[[VerifiedTarget], object]] = None


# Builds the exact environment of the Alembic child process.
# Parameters:
# - environ: the validated process environment.
# - verified: identity the child's own connection is bound to.
# - require_empty: whether the child must find an empty, unmigrated database.
# Returns:
# - A new mapping; no PG* variable, no dotenv loading, binding included.
def child_environment(environ: Mapping[str, str], verified: VerifiedTarget, require_empty: bool) -> dict:
    child = {name: environ[name] for name in CHILD_PASSTHROUGH if name in environ}
    child.update({name: environ[name] for name in CHILD_CONFIGURATION})
    # app_config calls load_dotenv(); a stray .env must not fill in anything.
    child["PYTHON_DOTENV_DISABLED"] = "1"
    child["VF_STAGING_BINDING"] = database.binding_payload(verified, require_empty)

    return child


def _run_alembic(arguments: Sequence[str], child: Mapping[str, str]) -> AlembicResult:
    secrets = [child.get("DATABASE_URL", ""), child.get("SUPABASE_PUBLISHABLE_KEY", "")]

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=str(API_DIRECTORY),
            env=dict(child),
            capture_output=True,
            text=True,
            timeout=ALEMBIC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return AlembicResult(124, "alembic timed out")

    return AlembicResult(completed.returncode, redact(completed.stdout + completed.stderr, secrets))


def _repository_heads() -> Sequence[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(API_DIRECTORY / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIRECTORY / "alembic"))

    return tuple(ScriptDirectory.from_config(config).get_heads())


def _expected_tables() -> Iterable[str]:
    # Importing the models loads app settings; the CLI sets the validated
    # environment (and disables dotenv) before this runs.
    from app.db.database_base import Base
    from app.db.database_models import import_database_models

    import_database_models()

    return tuple(Base.metadata.tables)


def _open_session(verified: VerifiedTarget):
    # Same session settings as app.db.database_session.SessionLocal, but bound
    # to an engine that re-verifies the identity on every connection.
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(autocommit=False, autoflush=False, bind=database.bound_engine(verified))()


def real_operations() -> Operations:
    return Operations(
        probe=database.probe_database,
        supabase_probe=probe_supabase_project,
        run_alembic=_run_alembic,
        repository_heads=_repository_heads,
        expected_tables=_expected_tables,
        describe=database.describe_data,
        destroy=database.destroy_application_objects,
        open_session=_open_session,
    )
