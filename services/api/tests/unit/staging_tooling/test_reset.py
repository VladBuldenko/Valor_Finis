"""Reset: separate, explicitly destructive, never automatic."""

import json
import os

import pytest

from staging_ops.errors import StagingRefused
from staging_ops.reset import interactive_confirm, reset

from . import helpers as h

PHRASE = f"STG-1/{h.DATABASE}@{h.STAGING_HOST}:5432"


def reset_probes():
    # verify, identity re-check, emptied check, build_to_head fresh, after-upgrade
    return [h.facts(unexpected_objects=7, alembic_revisions=(h.HEAD,)), h.facts(unexpected_objects=7, alembic_revisions=(h.HEAD,)), h.facts(), h.facts(), h.migrated_facts()]


def run(ops, confirm, environ=None, flag="staging", said=None, evidence_dir=None):
    return reset(flag, "STG-1", environ if environ is not None else h.good_environ(), h.approved(), ops.as_operations(), confirm, evidence_dir, say=(said.append if said is not None else (lambda _t: None)))


def refuse(ops, confirm, code, **kwargs):
    with pytest.raises(StagingRefused) as caught:
        run(ops, confirm, **kwargs)

    assert caught.value.code == code, caught.value
    assert ops.destroyed == 0 and not ops.alembic_arguments, "nothing may be destroyed or rebuilt on a refusal"
    assert not caught.value.mutated

    return caught.value


class TestRefusals:
    def test_missing_confirmation(self):
        refuse(h.FakeOps(probes=reset_probes()), None, "CONFIRMATION_MISSING")

    @pytest.mark.parametrize("typed", ["", "yes", "y", "STG-1", f"STG-1/valor_other_staging@{h.STAGING_HOST}:5432", f"STG-1/{h.DATABASE}@other-db.example.test:5432", PHRASE.lower(), PHRASE + " extra", " " + PHRASE])
    def test_confirmation_must_equal_the_exact_target_identity(self, typed):
        refuse(h.FakeOps(probes=reset_probes()), lambda _prompt: typed, "CONFIRMATION_MISMATCH")

    def test_a_confirmation_naming_a_different_database_is_refused(self):
        refuse(h.FakeOps(probes=reset_probes()), lambda _prompt: f"STG-1/valor_production_staging@{h.STAGING_HOST}:5432", "CONFIRMATION_MISMATCH")

    @pytest.mark.parametrize("flag", [None, "production", "test"])
    def test_environment_flag_gate_precedes_everything(self, flag):
        ops = h.FakeOps(probes=reset_probes())
        refuse(ops, lambda _prompt: PHRASE, "ENV_FLAG_MISSING" if flag is None else "ENV_FLAG_WRONG", flag=flag)
        assert "describe" not in ops.calls

    def test_identity_failures_refuse_before_any_prompt(self):
        asked = []
        ops = h.FakeOps(probes=reset_probes())

        refuse(ops, lambda prompt: asked.append(prompt) or PHRASE, "TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="other-db.example.test")))
        assert asked == []

    def test_production_target_refused(self):
        refuse(h.FakeOps(probes=reset_probes()), lambda _p: PHRASE, "DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(host=h.PRODUCTION_HOST)))

    def test_identity_that_changes_while_the_operator_confirms(self):
        probes = reset_probes()
        probes[1] = h.facts(postmaster_start="1700009999.0", unexpected_objects=7, alembic_revisions=(h.HEAD,))

        refuse(h.FakeOps(probes=probes), lambda _p: PHRASE, "IDENTITY_CHANGED")

    def test_non_interactive_input_cannot_confirm(self):
        # pytest runs without a terminal; `yes | ...` style automation must be refused.
        with pytest.raises(StagingRefused) as caught:
            interactive_confirm("prompt: ")

        assert caught.value.code == "CONFIRMATION_NOT_INTERACTIVE"


class TestConfirmedReset:
    def test_destroys_then_rebuilds_in_a_safe_order_and_describes_the_loss(self):
        ops = h.FakeOps(probes=reset_probes())
        said = []
        record = run(ops, lambda _p: PHRASE, said=said)

        assert ops.calls == ["supabase", "probe", "describe", "probe", "destroy", "probe", "heads", "probe", "alembic", "probe"]
        assert ops.alembic_arguments == [("upgrade", "head")]
        assert record.outcome == "OK" and record.details["rows_to_destroy"] == 15

        text = "\n".join(said)
        assert "PERMANENTLY DESTROY" in text and "accounts: 12 rows" in text and "Supabase Auth users" in text

    def test_prompt_shows_the_identity_to_type_but_nothing_secret(self):
        prompts = []

        run(h.FakeOps(probes=reset_probes()), lambda prompt: prompts.append(prompt) or PHRASE)

        assert PHRASE in prompts[0] and h.PASSWORD not in prompts[0]

    def test_database_not_empty_after_the_destroy_stops_the_rebuild(self):
        probes = reset_probes()
        probes[2] = h.facts(unexpected_objects=2)
        ops = h.FakeOps(probes=probes)

        with pytest.raises(StagingRefused) as caught:
            run(ops, lambda _p: PHRASE)

        assert caught.value.code == "POST_RESET_CHECK_FAILED" and caught.value.mutated
        assert not ops.alembic_arguments

    def test_evidence_of_a_reset_is_redacted(self, tmp_path):
        run(h.FakeOps(probes=reset_probes()), lambda _p: PHRASE, evidence_dir=str(tmp_path))
        (name,) = os.listdir(tmp_path)
        text = (tmp_path / name).read_text()

        assert json.loads(text)["operation"] == "reset"

        for secret in (h.PASSWORD, h.PUBLISHABLE_KEY, h.STAGING_HOST, "svc_user"):
            assert secret not in text
