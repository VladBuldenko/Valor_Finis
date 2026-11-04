"""
The staging reset is DISABLED / DEFERRED (owner-approved scope change).

These tests prove it cannot run, not merely that it warns: every callable and
command-line entry point refuses first, before configuration, targets,
connections or SQL, and no destructive capability exists to be reached.
"""

import ast
import importlib
import inspect
import pathlib
import re
import socket

import pytest

import staging_ops
from staging_ops import cli, database, operations as operations_module
from staging_ops.cli import EXIT_REFUSED, EXIT_USAGE, main
from staging_ops.errors import StagingRefused
from staging_ops.reset import reset

from . import helpers as h

PHRASE = f"STG-1/{h.DATABASE}@{h.STAGING_HOST}:5432"
PACKAGE = pathlib.Path(staging_ops.__file__).parent


class Untouchable:
    """Stands in for every capability; any call or attribute access fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the disabled reset touched {name}")


def refuses(*arguments, **keywords):
    with pytest.raises(StagingRefused) as caught:
        reset(*arguments, **keywords)

    assert caught.value.code == "RESET_DISABLED" and not caught.value.mutated
    assert "disabled" in caught.value.message and "newly provisioned" in caught.value.message

    return caught.value


class TestTheCallableRefusesFirst:
    def test_a_fully_valid_request_with_the_exact_phrase_is_still_refused_and_touches_nothing(self):
        ops = h.FakeOps()
        refuses("staging", "STG-1", h.good_environ(), h.approved(), ops.as_operations(), lambda _prompt: PHRASE, None, say=lambda _t: None)

        assert ops.calls == [] and ops.mutations == 0

    def test_nothing_is_read_from_the_arguments(self):
        refuses(Untouchable(), Untouchable(), Untouchable(), Untouchable(), Untouchable(), Untouchable())
        refuses()
        refuses(environment_flag="staging", staging_id="STG-1", environ=Untouchable(), approved=Untouchable(), operations=Untouchable())

    def test_it_does_not_write_evidence(self, tmp_path):
        refuses("staging", "STG-1", h.good_environ(), h.approved(), h.FakeOps().as_operations(), lambda _p: PHRASE, str(tmp_path))

        assert list(tmp_path.iterdir()) == []

    def test_the_old_interactive_confirmation_path_no_longer_exists(self):
        assert not hasattr(importlib.import_module("staging_ops.reset"), "interactive_confirm")


class TestTheCommandLineRefusesFirst:
    def test_reset_exits_11_with_no_capability_call(self, tmp_path, capsys):
        ops = h.FakeOps()
        code = main(["reset", "--environment", "staging", "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path), "--evidence-dir", str(tmp_path / "evidence")], h.good_environ(), ops.as_operations(), say=lambda _t: None)
        captured = capsys.readouterr()

        assert code == EXIT_REFUSED and ops.calls == [] and ops.mutations == 0
        assert "RESET_DISABLED" in captured.err and not (tmp_path / "evidence").exists()

    def test_it_is_refused_before_the_approved_targets_are_read(self, tmp_path, capsys):
        # The file does not exist: a command that reached it would fail with a different code.
        code = main(["reset", "--approved-targets", str(tmp_path / "missing.json")], h.good_environ(), h.FakeOps().as_operations(), say=lambda _t: None)

        assert code == EXIT_REFUSED and "RESET_DISABLED" in capsys.readouterr().err

    def test_it_is_refused_even_without_any_other_argument(self, capsys):
        assert main(["reset"], {}, h.FakeOps().as_operations(), say=lambda _t: None) == EXIT_REFUSED
        assert "RESET_DISABLED" in capsys.readouterr().err

    def test_it_does_not_open_a_database_connection_or_any_socket(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine

        import psycopg2

        def forbidden(*_a, **_k):
            raise AssertionError("a connection was attempted")

        monkeypatch.setattr(database, "create_engine", forbidden)
        monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
        monkeypatch.setattr(psycopg2, "connect", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(socket.socket, "connect", forbidden)

        # The REAL operations are wired, so any attempted use would reach a driver and fail the test.
        code = main(["reset", "--environment", "staging", "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path), "--evidence-dir", str(tmp_path / "e")], h.good_environ(), None, say=lambda _t: None)

        assert code == EXIT_REFUSED

    @pytest.mark.parametrize("flag", ["--force", "--yes", "-y", "--skip-confirmation", "--confirm", "--no-verify"])
    def test_no_flag_can_enable_it(self, flag, tmp_path):
        ops = h.FakeOps()

        assert main(["reset", flag, "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path)], h.good_environ(), ops.as_operations()) in (EXIT_USAGE, EXIT_REFUSED)
        assert ops.calls == []

    def test_the_module_docstring_lists_no_reset_invocation(self):
        assert not re.search(r"python -m staging_ops reset\s+--", inspect.getsource(cli))

    def test_main_no_longer_accepts_a_confirmation_callback(self):
        assert "confirm" not in inspect.signature(main).parameters


class TestNoDestructiveCapabilityExists:
    """The strongest guarantee: there is nothing to call. Grep-level checks over the whole package."""

    def test_the_operations_bundle_has_no_destructive_field(self):
        fields = set(operations_module.Operations.__dataclass_fields__)

        assert not fields & {"destroy", "describe", "external_dependents", "reset"}

    def test_the_database_module_has_no_removal_primitive(self):
        assert not [name for name in dir(database) if re.search(r"destroy|drop|reset|truncate", name, re.I)]

    def test_the_removed_scope_module_cannot_be_imported(self):
        with pytest.raises(ImportError):
            importlib.import_module("staging_ops.reset_scope")

        assert not (PACKAGE / "reset_scope.py").exists()

    def test_no_string_in_the_package_can_execute_a_removal(self):
        statement = re.compile(r"^\s*(DROP|TRUNCATE|ALTER\s+\w+\s+.*\bDROP\b|DELETE\s+FROM)\b|\bCASCADE\b", re.I)
        offenders = []

        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant)}

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and statement.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno}: {node.value[:60]!r}")

        assert offenders == []

    def test_no_pipeline_script_or_runbook_command_invokes_the_reset(self):
        root = PACKAGE.parents[2]
        runbook_files = list((root / "docs" / "operations" / "staging").rglob("*.md")) + list((root / "docs" / "operations" / "staging").rglob("*.sh"))
        pattern = re.compile(r"staging_ops\s+reset\s+-", re.I)

        assert runbook_files
        assert [str(path) for path in runbook_files if pattern.search(path.read_text(encoding="utf-8"))] == []
