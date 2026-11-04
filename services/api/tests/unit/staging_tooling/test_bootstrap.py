"""Bootstrap orchestration: refusals never reach the mutation, the happy path is exact."""

import json
import os
from dataclasses import replace

import pytest

from staging_ops.bootstrap import bootstrap
from staging_ops.errors import StagingRefused

from . import helpers as h


def run(ops, environ=None, flag="staging", staging="STG-1", approved=None, evidence_dir=None):
    return bootstrap(flag, staging, environ if environ is not None else h.good_environ(), approved or h.approved(), ops.as_operations(), evidence_dir, say=lambda _text: None)


def refuse(ops, code, **kwargs):
    with pytest.raises(StagingRefused) as caught:
        run(ops, **kwargs)

    assert caught.value.code == code, caught.value
    assert ops.mutations == 0, "the mutation command must not run on a refusal"
    assert not caught.value.mutated

    return caught.value


class TestHappyPath:
    def test_builds_to_head_with_exactly_one_upgrade_head(self):
        ops = h.FakeOps()
        record = run(ops)

        assert ops.alembic_arguments == [("upgrade", "head")]
        assert ops.calls == ["supabase", "probe", "heads", "probe", "alembic", "probe"]
        assert record.outcome == "OK"
        assert record.details["alembic_head"] == record.details["alembic_current"] == h.HEAD
        assert record.database_oid == h.OID

    def test_the_child_process_environment_is_a_whitelist_with_the_binding(self):
        ops = h.FakeOps()
        run(ops, environ=h.good_environ(SUPABASE_SECRET_KEY="must-not-pass", PGPASSWORD="x", UNRELATED="y", PYTHONPATH="/tmp/evil"))
        child = ops.alembic_environments[0]

        assert set(child) <= {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "DATABASE_URL", "AUTH_MODE", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "PYTHON_DOTENV_DISABLED", "VF_STAGING_BINDING"}
        assert child["PYTHON_DOTENV_DISABLED"] == "1"
        assert json.loads(child["VF_STAGING_BINDING"]) == {"database": h.DATABASE, "oid": h.OID, "postmaster_start": h.POSTMASTER, "require_empty": True}

    def test_writes_sanitized_evidence(self, tmp_path):
        run(h.FakeOps(), evidence_dir=str(tmp_path))
        (name,) = os.listdir(tmp_path)
        text = (tmp_path / name).read_text()
        data = json.loads(text)

        assert data["outcome"] == "OK" and data["staging_id"] == "STG-1" and data["database"] == h.DATABASE
        assert data["host_fingerprint"].startswith("fp1:")

        for secret in (h.PASSWORD, h.PUBLISHABLE_KEY, h.STAGING_HOST, "svc_user", "postgresql://"):
            assert secret not in text


class TestRefusalsNeverMutate:
    def test_missing_or_wrong_environment_flag(self):
        refuse(h.FakeOps(), "ENV_FLAG_MISSING", flag=None)
        refuse(h.FakeOps(), "ENV_FLAG_WRONG", flag="production")

    def test_host_not_allowlisted(self):
        refuse(h.FakeOps(), "TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="other-db.example.test")))

    def test_production_host_and_project(self):
        refuse(h.FakeOps(), "DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(host=h.PRODUCTION_HOST)))
        refuse(h.FakeOps(), "DENYLIST_HIT", environ=h.good_environ(SUPABASE_URL=f"https://{h.PRODUCTION_REF}.supabase.co"))

    def test_empty_denylist(self):
        refuse(h.FakeOps(), "DENYLIST_EMPTY", approved=h.approved(lambda d: d["production_denylist"].update(database_hosts=[])))

    def test_supabase_project_not_verified_live(self):
        error = StagingRefused("SUPABASE_PROBE_FAILED", "the staging Supabase project did not accept the configured key")

        refuse(h.FakeOps(supabase_error=error), "SUPABASE_PROBE_FAILED")

    def test_nonempty_database(self):
        refuse(h.FakeOps(probes=[h.facts(), h.facts(unexpected_objects=3)]), "DATABASE_NOT_EMPTY")

    def test_database_that_became_nonempty_after_the_first_probe(self):
        # Emptiness is judged on the probe taken right before the mutation, not the first one.
        refuse(h.FakeOps(probes=[h.facts(), h.facts(unexpected_objects=1)]), "DATABASE_NOT_EMPTY")

    @pytest.mark.parametrize("revisions", [("c4d8a2f6e193",), ("deadbeef0000",), ()])
    def test_unexpected_alembic_revision(self, revisions):
        refuse(h.FakeOps(probes=[h.facts(), h.facts(alembic_revisions=revisions)]), "REVISION_UNEXPECTED")

    def test_more_than_one_repository_head(self):
        refuse(h.FakeOps(heads=("aaa", "bbb")), "HEADS_NOT_SINGLE")
        refuse(h.FakeOps(heads=()), "HEADS_NOT_SINGLE")

    def test_connected_database_differs_from_the_validated_target(self):
        refuse(h.FakeOps(probes=[h.facts(database="valor_other_staging")]), "CONNECTED_DATABASE_MISMATCH")
        refuse(h.FakeOps(probes=[h.facts(oid=h.OID + 7)]), "CONNECTED_OID_MISMATCH")

    @pytest.mark.parametrize("change", [dict(oid=7), dict(database="valor_other_staging"), dict(postmaster_start="1700009999.0")])
    def test_identity_changes_between_the_check_and_the_mutation(self, change):
        refuse(h.FakeOps(probes=[h.facts(), h.facts(**change)]), "IDENTITY_CHANGED")

    def test_every_single_failing_identity_check_refuses(self):
        # Each case breaks exactly one check of the chain; none may reach the mutation.
        cases = [
            dict(flag=None),
            dict(flag="prod"),
            dict(staging="STG-2"),
            dict(environ=h.good_environ(PGHOST="x")),
            dict(environ=h.good_environ(AUTH_MODE="development")),
            dict(environ=h.good_environ(SUPABASE_URL="https://otherprojectrefabcdef.supabase.co")),
            dict(environ=h.good_environ(DATABASE_URL=h.database_url(database="valor_x_staging"))),
            dict(environ=h.good_environ(DATABASE_URL=h.database_url(query=""))),
            dict(environ=h.good_environ(DATABASE_URL="garbage")),
            dict(approved=h.approved(lambda d: d["staging"][0]["database"].pop("oid"))),
        ]

        for case in cases:
            ops = h.FakeOps()

            with pytest.raises(StagingRefused):
                run(ops, **case)

            assert ops.mutations == 0, case


class TestFailuresAfterTheMutationBegan:
    def test_failed_upgrade_is_reported_as_a_mutation_failure_with_redacted_output(self):
        leaking = f"connection failed postgresql://svc_user:{h.PASSWORD}@{h.STAGING_HOST}:5432/{h.DATABASE} password={h.PASSWORD} key {h.PUBLISHABLE_KEY}"
        ops = h.FakeOps(alembic_returncode=1, alembic_output=leaking)
        said = []

        with pytest.raises(StagingRefused) as caught:
            bootstrap("staging", "STG-1", h.good_environ(), h.approved(), ops.as_operations(), None, say=said.append)

        assert caught.value.code == "UPGRADE_FAILED" and caught.value.mutated
        shown = "\n".join(said) + str(caught.value)

        for secret in (h.PASSWORD, h.PUBLISHABLE_KEY, h.STAGING_HOST, "svc_user"):
            assert secret not in shown

    def test_post_check_revision_mismatch(self):
        ops = h.FakeOps(probes=[h.facts(), h.facts(), replace(h.migrated_facts(), alembic_revisions=("otherrevision",))])

        with pytest.raises(StagingRefused) as caught:
            run(ops)

        assert caught.value.code == "REVISION_MISMATCH" and caught.value.mutated

    def test_post_check_unexpected_tables(self):
        extra = replace(h.migrated_facts(), public_tables=("accounts", "alembic_version", "goals", "stray_table"))

        with pytest.raises(StagingRefused) as caught:
            run(h.FakeOps(probes=[h.facts(), h.facts(), extra]))

        assert caught.value.code == "SCHEMA_UNEXPECTED_OBJECTS"

    def test_identity_changed_during_the_upgrade(self):
        moved = replace(h.migrated_facts(), postmaster_start="1700009999.0")

        with pytest.raises(StagingRefused) as caught:
            run(h.FakeOps(probes=[h.facts(), h.facts(), moved]))

        assert caught.value.code == "IDENTITY_CHANGED"

    def test_evidence_is_written_for_a_refusal_too(self, tmp_path):
        ops = h.FakeOps()

        with pytest.raises(StagingRefused):
            run(ops, flag="production", evidence_dir=str(tmp_path))

        (name,) = os.listdir(tmp_path)
        data = json.loads((tmp_path / name).read_text())

        assert data["outcome"] == "REFUSED" and data["code"] == "ENV_FLAG_WRONG"
