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
from staging_ops import reset_scope
from staging_ops.seed import _verify_owner_consistency

from . import helpers as h


class Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeConnection:
    def __init__(self, lock=True, remaining=0):
        self.lock, self.remaining = lock, remaining
        self.executed = []

    def exec_driver_sql(self, sql):
        self.executed.append(sql)

        if "pg_try_advisory_xact_lock" in sql:
            return Scalar(self.lock)

        return Scalar(self.remaining)


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


def run_destroy(monkeypatch, connection, scope=lambda _connection: 4):
    engine = FakeEngine(connection)
    monkeypatch.setattr(database, "bound_engine", lambda _verified: engine)
    monkeypatch.setattr(database.reset_scope, "drop_scope", scope)

    return engine


class TestDestroyControlFlow:
    """SIMULATED connections: control flow only. The SQL itself is proven against a real server."""

    def test_commits_only_when_nothing_unexpected_remains(self, monkeypatch, verified):
        connection = FakeConnection(remaining=0)
        engine = run_destroy(monkeypatch, connection)

        assert database.destroy_application_objects(verified) == 4
        assert engine.committed and not engine.rolled_back and engine.disposed
        assert connection.executed[-1] == database.binding.UNEXPECTED_OBJECTS_SQL

    def test_objects_remaining_after_the_drops_roll_everything_back(self, monkeypatch, verified):
        engine = run_destroy(monkeypatch, FakeConnection(remaining=3))

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "RESET_INCOMPLETE" and engine.rolled_back and not engine.committed

    def test_a_busy_lock_runs_no_scope_statement(self, monkeypatch, verified):
        called = []
        engine = run_destroy(monkeypatch, FakeConnection(lock=False), scope=lambda _c: called.append(1))

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "LOCK_BUSY" and not called and engine.rolled_back

    @pytest.mark.parametrize("code", ["EXTERNAL_DEPENDENCIES", "EXTERNAL_OBJECT_CHANGED", "RESET_BLOCKED"])
    def test_a_scope_refusal_rolls_back_and_keeps_its_code(self, monkeypatch, verified, code):
        def scope(_connection):
            raise StagingRefused(code, "scope")

        engine = run_destroy(monkeypatch, FakeConnection(), scope=scope)

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == code and engine.rolled_back and not engine.committed

    def test_a_driver_error_is_reported_without_its_text(self, monkeypatch, verified):
        def scope(_connection):
            raise RuntimeError(f"connection to server at {h.STAGING_HOST} failed for user svc_user")

        engine = run_destroy(monkeypatch, FakeConnection(), scope=scope)

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "RESET_FAILED" and h.STAGING_HOST not in str(caught.value) and engine.rolled_back


class TestScopeSqlIsNeverCascading:
    """The destroy path must not contain a CASCADE; a reviewer can grep this guarantee."""

    def test_no_executable_string_in_the_destroy_path_contains_cascade(self):
        import ast
        import inspect

        for module in (reset_scope, database):
            tree = ast.parse(inspect.getsource(module))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant)}
            offenders = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and "CASCADE" in node.value.upper()]

            assert offenders == [], module.__name__

        assert reset_scope.DROP_ORDER

    def test_every_drop_statement_is_explicit_restrict(self):
        statements = []

        class Recording:
            def begin_nested(self):
                class Nested:
                    def commit(self):
                        pass

                    def rollback(self):
                        pass

                return Nested()

            def exec_driver_sql(self, sql):
                statements.append(sql)

        reset_scope._try_drop(Recording(), "TABLE", ['"public"."a b"', '"public"."c"'])

        assert statements == ['DROP TABLE IF EXISTS "public"."a b", "public"."c" RESTRICT']


class FakeRows:
    def __init__(self, rows=(), value=0):
        self.rows, self.value = rows, value

    def all(self):
        return list(self.rows)

    def scalar(self):
        return self.value


class FakeDialect:
    class identifier_preparer:  # noqa: N801 - mirrors the SQLAlchemy attribute
        @staticmethod
        def quote(name):
            return f'"{name}"'


class FakeBind:
    dialect = FakeDialect


class OwnerSession:
    def __init__(self, relationships, mismatches):
        self.relationships, self.mismatches = relationships, mismatches
        self.statements = []
        self.rollbacks = 0

    def get_bind(self):
        return FakeBind

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)

        if "array_length(k.conkey, 1) = 1" in sql:
            return FakeRows(rows=self.relationships)

        if "array_length(k.conkey, 1) > 1" in sql:
            return FakeRows(value=7)

        return FakeRows(value=self.mismatches)

    def rollback(self):
        self.rollbacks += 1


class TestOwnerConsistencyCheck:
    RELATIONSHIPS = [("goal_transactions", "goal_id", "goals", "id"), ("budgets", "category_id", "categories", "id")]

    def test_reports_exactly_what_was_checked_and_what_was_not(self):
        session = OwnerSession(self.RELATIONSHIPS, 0)

        details = _verify_owner_consistency(session)

        assert details["checked_relationships"] == ["goal_transactions.goal_id->goals.id", "budgets.category_id->categories.id"]
        assert details["composite_user_foreign_keys_enforced_by_database"] == 7
        assert "API-level" in details["not_covered"] and "sql-single-column" in details["method"]
        assert session.rollbacks >= 1

    def test_a_cross_user_reference_fails_the_seed(self):
        with pytest.raises(StagingRefused) as caught:
            _verify_owner_consistency(OwnerSession(self.RELATIONSHIPS, 2))

        assert caught.value.code == "SEED_OWNER_MISMATCH" and "goal_transactions.goal_id" in caught.value.message

    def test_an_empty_relationship_list_is_reported_not_passed_off_as_coverage(self):
        assert _verify_owner_consistency(OwnerSession([], 0))["checked_relationships"] == []


class TestRedactionOfValuesWithoutAPattern:
    def test_a_bare_password_is_removed_only_by_exact_match(self):
        assert "hunter2-fixture" not in redact("login failed for hunter2-fixture today", ["hunter2-fixture"])
        assert "hunter2-fixture" in redact("login failed for hunter2-fixture today")
