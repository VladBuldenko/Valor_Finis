"""Command line wiring: usage errors, exit codes, no leaks."""

import json
import os

from staging_ops.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main

from . import helpers as h
from .test_reset import PHRASE, reset_probes


def args(tmp_path, command, *extra, flag=True):
    base = [command, "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path), "--evidence-dir", str(tmp_path / "evidence")]

    return base + (["--environment", "staging"] if flag else []) + list(extra)


class TestUsage:
    def test_unknown_command_and_missing_arguments(self, tmp_path):
        assert main(["explode"], h.good_environ(), h.FakeOps().as_operations()) == EXIT_USAGE
        assert main(["bootstrap"], h.good_environ(), h.FakeOps().as_operations()) == EXIT_USAGE

    def test_mutating_commands_need_an_evidence_directory(self, tmp_path):
        ops = h.FakeOps()
        code = main(["bootstrap", "--environment", "staging", "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path)], h.good_environ(), ops.as_operations())

        assert code == EXIT_USAGE and ops.mutations == 0

    def test_seed_needs_a_users_file(self, tmp_path):
        assert main(args(tmp_path, "seed"), h.good_environ(), h.FakeOps().as_operations()) == EXIT_USAGE

    def test_there_is_no_force_or_yes_flag(self, tmp_path):
        for flag in ("--force", "--yes", "-y", "--skip-confirmation", "--no-verify"):
            assert main(args(tmp_path, "reset", flag), h.good_environ(), h.FakeOps().as_operations()) == EXIT_USAGE


class TestExitCodes:
    def test_refusal_exits_11_without_mutating_and_prints_no_secret(self, tmp_path, capsys):
        ops = h.FakeOps()
        code = main(args(tmp_path, "bootstrap", flag=False), h.good_environ(), ops.as_operations(), say=print)
        captured = capsys.readouterr()

        assert code == EXIT_REFUSED and ops.mutations == 0
        assert "ENV_FLAG_MISSING" in captured.err

        for secret in (h.PASSWORD, h.PUBLISHABLE_KEY, h.STAGING_HOST, "svc_user"):
            assert secret not in captured.out + captured.err

    def test_bootstrap_ok(self, tmp_path):
        assert main(args(tmp_path, "bootstrap"), h.good_environ(), h.FakeOps().as_operations(), say=lambda _t: None) == EXIT_OK

    def test_failure_after_the_mutation_began_exits_12(self, tmp_path):
        assert main(args(tmp_path, "bootstrap"), h.good_environ(), h.FakeOps(alembic_returncode=1).as_operations(), say=lambda _t: None) == EXIT_FAILED

    def test_reset_refuses_without_the_exact_phrase(self, tmp_path):
        ops = h.FakeOps(probes=reset_probes())

        assert main(args(tmp_path, "reset"), h.good_environ(), ops.as_operations(), confirm=lambda _p: "yes", say=lambda _t: None) == EXIT_REFUSED
        assert ops.destroyed == 0

    def test_reset_with_the_exact_phrase(self, tmp_path):
        ops = h.FakeOps(probes=reset_probes())

        assert main(args(tmp_path, "reset"), h.good_environ(), ops.as_operations(), confirm=lambda _p: PHRASE, say=lambda _t: None) == EXIT_OK
        assert ops.destroyed == 1

    def test_the_cli_never_confirms_a_reset_on_its_own(self, tmp_path):
        # No injected confirm: the real interactive prompt is used and refuses a non-terminal.
        ops = h.FakeOps(probes=reset_probes())

        assert main(args(tmp_path, "reset"), h.good_environ(), ops.as_operations(), say=lambda _t: None) == EXIT_REFUSED
        assert ops.destroyed == 0

    def test_identify_prints_the_oid_for_the_owner_and_is_read_only(self, tmp_path):
        said = []
        pinned_free = h.approved_document()
        pinned_free["staging"][0]["database"].pop("oid")
        arguments = ["identify", "--environment", "staging", "--staging", "STG-1", "--approved-targets", h.write_approved_file(tmp_path, pinned_free)]
        ops = h.FakeOps(probes=[h.facts()])

        assert main(arguments, h.good_environ(), ops.as_operations(), say=said.append) == EXIT_OK
        assert str(h.OID) in "\n".join(said) and "empty-and-unmigrated" in "\n".join(said)
        assert ops.mutations == 0 and ops.calls == ["supabase", "probe"]

    def test_the_process_environment_gets_dotenv_disabled(self, tmp_path):
        main(args(tmp_path, "bootstrap"), h.good_environ(), h.FakeOps().as_operations(), say=lambda _t: None)

        assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"

    def test_seed_users_file_must_be_valid_json(self, tmp_path):
        users = tmp_path / "users.json"
        users.write_text("nope")
        ops = h.FakeOps()

        assert main(args(tmp_path, "seed", "--users-file", str(users)), h.good_environ(), ops.as_operations(), say=lambda _t: None) == EXIT_REFUSED
        assert ops.sessions == 0
        json.dumps({})
