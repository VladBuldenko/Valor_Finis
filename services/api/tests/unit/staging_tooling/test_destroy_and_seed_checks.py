"""
Checks that cannot be provoked through a real catalog: simulated connections.

These tests use a recording fake in place of a database. They prove the control
flow of the safety checks only; the real-database behaviour is covered in
tests/integration/staging_tooling (SIMULATED, not database acceptance).
"""

import contextlib

import pytest

from staging_ops import database
from staging_ops.errors import StagingRefused
from staging_ops.identity import verify_configuration, verify_facts
from staging_ops.redaction import redact
from staging_ops.seed import _verify_isolation

from . import helpers as h


class Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeSession:
    def __init__(self, mismatches):
        self.mismatches = mismatches
        self.rollbacks = 0

    def execute(self, _statement):
        return Scalar(self.mismatches)

    def rollback(self):
        self.rollbacks += 1


class FakeConnection:
    def __init__(self, lock=True, remaining=0, statements=("DROP TABLE IF EXISTS public.a CASCADE",)):
        self.lock, self.remaining, self.statements = lock, remaining, statements
        self.executed = []

    def exec_driver_sql(self, sql):
        self.executed.append(sql)

        if "pg_try_advisory_xact_lock" in sql:
            return Scalar(self.lock)

        if sql.startswith("DROP"):
            return Scalar(None)

        return Scalar(self.remaining)

    def execute(self, _statement):
        return [(statement,) for statement in self.statements]


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.committed = False
        self.rolled_back = False
        self.disposed = False

    @contextlib.contextmanager
    def begin(self):
        try:
            yield self.connection
            self.committed = True
        except BaseException:
            self.rolled_back = True
            raise

    def dispose(self):
        self.disposed = True


@pytest.fixture
def verified():
    configured = verify_configuration("staging", "STG-1", h.good_environ(), h.approved())

    return verify_facts(configured, h.facts())


def run_destroy(monkeypatch, verified, connection):
    engine = FakeEngine(connection)
    monkeypatch.setattr(database, "bound_engine", lambda _verified: engine)

    return engine


class TestDestroyControlFlow:
    def test_commits_only_when_nothing_unexpected_remains(self, monkeypatch, verified):
        connection = FakeConnection(remaining=0)
        engine = run_destroy(monkeypatch, verified, connection)

        assert database.destroy_application_objects(verified) == 1
        assert engine.committed and not engine.rolled_back and engine.disposed
        assert connection.executed[-1] == database.binding.UNEXPECTED_OBJECTS_SQL

    def test_objects_remaining_after_the_drops_roll_everything_back(self, monkeypatch, verified):
        engine = run_destroy(monkeypatch, verified, FakeConnection(remaining=3))

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "RESET_INCOMPLETE" and engine.rolled_back and not engine.committed

    def test_a_busy_lock_drops_nothing(self, monkeypatch, verified):
        connection = FakeConnection(lock=False)
        engine = run_destroy(monkeypatch, verified, connection)

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "LOCK_BUSY" and not any(sql.startswith("DROP") for sql in connection.executed)
        assert engine.rolled_back


class TestSeedIsolationCheck:
    def test_passes_when_no_object_references_another_user(self):
        session = FakeSession(0)

        _verify_isolation(session)

        assert session.rollbacks == 1

    def test_a_cross_user_reference_fails_the_seed(self):
        with pytest.raises(StagingRefused) as caught:
            _verify_isolation(FakeSession(2))

        assert caught.value.code == "SEED_ISOLATION_BROKEN"


class TestRedactionOfValuesWithoutAPattern:
    def test_a_bare_password_is_removed_only_by_exact_match(self):
        assert "hunter2-fixture" not in redact("login failed for hunter2-fixture today", ["hunter2-fixture"])
        assert "hunter2-fixture" in redact("login failed for hunter2-fixture today")
