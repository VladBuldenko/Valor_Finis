"""
Seed checks that cannot be provoked through a real catalog: simulated connections.

These tests use a recording fake in place of a database. They prove the control
flow of the safety checks only; the real-database behaviour is covered in
tests/integration/staging_tooling (SIMULATED, not database acceptance).
"""

import pytest

from staging_ops.errors import StagingRefused
from staging_ops.redaction import redact
from staging_ops.seed import _verify_owner_consistency

from . import helpers as h


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
