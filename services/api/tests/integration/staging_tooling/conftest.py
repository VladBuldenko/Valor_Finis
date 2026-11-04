"""
Disposable local PostgreSQL for the staging tooling integration tests.

The fixture starts its OWN throw-away cluster (initdb in a temporary directory,
loopback only, random port, no Unix socket) and removes it afterwards. It never
touches an existing server, the development database or any remote host. When
no PostgreSQL server binaries are installed the tests are skipped with an
explicit reason: that is "NOT RUN", not a pass.
"""

import contextlib
import glob
import os
import shutil
import socket
import subprocess
from typing import List, Optional

import psycopg2
import pytest


def _find_binaries() -> Optional[str]:
    candidates: List[str] = []

    if os.environ.get("VF_QA1_PG_BIN"):
        candidates.append(os.environ["VF_QA1_PG_BIN"])

    on_path = shutil.which("initdb")

    if on_path:
        candidates.append(os.path.dirname(on_path))

    candidates += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    candidates += sorted(glob.glob("/Applications/Postgres.app/Contents/Versions/*/bin"), reverse=True)
    candidates += sorted(glob.glob("/opt/homebrew/opt/postgresql@*/bin"), reverse=True)

    for directory in candidates:
        if all(os.access(os.path.join(directory, name), os.X_OK) for name in ("initdb", "pg_ctl", "postgres")):
            return directory

    return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))

        return probe.getsockname()[1]


class LocalCluster:
    host = "127.0.0.1"
    user = "postgres"

    def __init__(self, port: int) -> None:
        self.port = port
        self._counter = 0

    def url(self, database: str) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/{database}"

    def connect(self, database: str = "postgres"):
        connection = psycopg2.connect(host=self.host, port=self.port, user=self.user, dbname=database)
        connection.autocommit = True

        return connection

    # Creates an empty database named vfqa1_<n>_staging and returns (name, oid).
    def create_database(self, suffix: str = "staging") -> tuple:
        self._counter += 1
        name = f"vfqa1_{os.getpid()}_{self._counter}_{suffix}"

        with contextlib.closing(self.connect()) as connection, connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{name}"')
            cursor.execute("SELECT oid::bigint FROM pg_database WHERE datname = %s", (name,))

            return name, int(cursor.fetchone()[0])


@pytest.fixture(scope="session")
def pg_bin():
    """Directory holding psql and the server binaries; the tests skip (NOT RUN) when there is none."""

    binaries = _find_binaries()

    if binaries is None or not os.access(os.path.join(binaries, "psql"), os.X_OK):
        pytest.skip("NOT RUN: no psql found next to the PostgreSQL server binaries; set VF_QA1_PG_BIN")

    return binaries


@pytest.fixture(scope="session")
def local_cluster(tmp_path_factory):
    binaries = _find_binaries()

    if binaries is None:
        pytest.skip("NOT RUN: no PostgreSQL server binaries (initdb, pg_ctl, postgres) found; set VF_QA1_PG_BIN")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("NOT RUN: PostgreSQL refuses to start as root")

    base = tmp_path_factory.mktemp("vfqa1pg")
    data = str(base / "data")
    log = str(base / "server.log")
    port = _free_port()
    subprocess.run([os.path.join(binaries, "initdb"), "-D", data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--locale=C", "--no-sync"], check=True, capture_output=True)
    options = f"-c listen_addresses=127.0.0.1 -c port={port} -c unix_socket_directories= -c fsync=off -c max_connections=40"
    subprocess.run([os.path.join(binaries, "pg_ctl"), "-D", data, "-o", options, "-l", log, "-w", "start"], check=True, capture_output=True)

    try:
        yield LocalCluster(port)
    finally:
        subprocess.run([os.path.join(binaries, "pg_ctl"), "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True)
