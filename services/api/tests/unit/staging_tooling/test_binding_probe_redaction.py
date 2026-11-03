"""Alembic binding hook, Supabase probe and redaction."""

import json
import urllib.error

import pytest

from staging_ops import binding
from staging_ops.errors import StagingRefused
from staging_ops.identity import verify_configuration
from staging_ops.redaction import fingerprint, redact
from staging_ops.supabase_probe import _NoRedirect, probe_supabase_project

from . import helpers as h


class Result:
    def __init__(self, scalar=None, row=None):
        self._scalar, self._row = scalar, row

    def scalar(self):
        return self._scalar

    def one(self):
        return self._row


class FakeConnection:
    def __init__(self, lock=True, identity=(h.DATABASE, h.OID, h.POSTMASTER, False, 170002), has_alembic=False, unexpected=0):
        self.lock, self.identity, self.has_alembic, self.unexpected = lock, identity, has_alembic, unexpected
        self.statements = []

    def exec_driver_sql(self, sql):
        self.statements.append(sql)

        if "pg_try_advisory_xact_lock" in sql:
            return Result(scalar=self.lock)

        if sql == binding.IDENTITY_SQL:
            return Result(row=self.identity)

        if sql == binding.ALEMBIC_TABLE_SQL:
            return Result(scalar=self.has_alembic)

        return Result(scalar=self.unexpected)


def payload(**overrides):
    return json.dumps({"database": h.DATABASE, "oid": h.OID, "postmaster_start": h.POSTMASTER, "require_empty": True, **overrides})


def refused(connection, raw):
    with pytest.raises(RuntimeError) as caught:
        binding.verify_migration_binding(connection, raw)

    return str(caught.value)


class TestMigrationBinding:
    def test_accepts_the_verified_empty_database(self):
        binding.verify_migration_binding(FakeConnection(), payload())

    @pytest.mark.parametrize("raw", ["", "not json", "{}", json.dumps({"database": "x"}), json.dumps({"database": "x", "oid": "a", "postmaster_start": "1", "require_empty": True})])
    def test_malformed_binding(self, raw):
        assert refused(FakeConnection(), raw) == "VF_STAGING_BINDING_INVALID"

    def test_another_run_holds_the_lock(self):
        assert refused(FakeConnection(lock=False), payload()) == "VF_STAGING_LOCK_BUSY"

    @pytest.mark.parametrize(
        "identity",
        [
            ("valor_other_staging", h.OID, h.POSTMASTER, False, 170002),
            (h.DATABASE, h.OID + 1, h.POSTMASTER, False, 170002),
            (h.DATABASE, h.OID, "1700009999.0", False, 170002),
            (h.DATABASE, h.OID, h.POSTMASTER, True, 170002),
        ],
    )
    def test_the_migration_connection_reached_a_different_database(self, identity):
        connection = FakeConnection(identity=identity)

        assert refused(connection, payload()) == "VF_STAGING_BINDING_MISMATCH"
        assert not any("count(*)" in statement for statement in connection.statements), "no further statements after a mismatch"

    def test_bootstrap_requires_an_empty_unmigrated_database(self):
        assert refused(FakeConnection(has_alembic=True), payload()) == "VF_STAGING_NOT_EMPTY"
        assert refused(FakeConnection(unexpected=2), payload()) == "VF_STAGING_NOT_EMPTY"

    def test_emptiness_is_not_required_when_the_binding_does_not_ask(self):
        binding.verify_migration_binding(FakeConnection(unexpected=5), payload(require_empty=False))


class TestSupabaseProbe:
    def configured(self):
        return verify_configuration("staging", "STG-1", h.good_environ(), h.approved())

    class Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_accepts_a_200_from_the_validated_project_host_only(self):
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, request.get_header("Apikey"), timeout))
            return self.Response(200)

        probe_supabase_project(self.configured(), h.good_environ(), opener)

        assert seen == [(f"https://{h.STAGING_REF}.supabase.co/auth/v1/settings", h.PUBLISHABLE_KEY, 5)]

    @pytest.mark.parametrize("make_failure", [lambda: urllib.error.URLError("down"), lambda: urllib.error.HTTPError("u", 401, "no", {}, None), lambda: OSError("x"), lambda: TimeoutError()])
    def test_transport_errors_are_a_refusal_without_details(self, make_failure):
        def opener(request, timeout):
            raise make_failure()

        with pytest.raises(StagingRefused) as caught:
            probe_supabase_project(self.configured(), h.good_environ(), opener)

        assert caught.value.code == "SUPABASE_PROBE_FAILED" and h.PUBLISHABLE_KEY not in str(caught.value)

    def test_non_200_is_a_refusal(self):
        with pytest.raises(StagingRefused):
            probe_supabase_project(self.configured(), h.good_environ(), lambda request, timeout: self.Response(204))

    def test_redirects_are_never_followed_so_the_key_cannot_travel(self):
        assert _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example.test") is None


class TestRedaction:
    def test_known_secrets_urls_and_keys_are_removed(self):
        text = f"fail postgresql://u:{h.PASSWORD}@{h.STAGING_HOST}:5432/db Bearer abc.def password={h.PASSWORD} key {h.PUBLISHABLE_KEY} https://x.example.test/a?b=c"
        cleaned = redact(text, [h.PASSWORD])

        for secret in (h.PASSWORD, h.PUBLISHABLE_KEY, h.STAGING_HOST, "abc.def", "x.example.test"):
            assert secret not in cleaned

    def test_jwt_shaped_values_are_removed(self):
        jwt = "ey" + "J" + "hbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2lnbmF0dXJl"

        assert jwt not in redact(f"token {jwt}")

    def test_libpq_connection_errors_are_removed(self):
        assert h.STAGING_HOST not in redact(f'connection to server at "{h.STAGING_HOST}" (192.0.2.10), port 5432 failed')

    def test_fingerprint_is_stable_one_way_and_domain_separated(self):
        assert fingerprint("db-host", "a:1") == fingerprint("db-host", "a:1")
        assert fingerprint("db-host", "a:1") != fingerprint("api", "a:1")
        assert len(fingerprint("db-host", "a:1")) == len("fp1:") + 16 and "a:1" not in fingerprint("db-host", "a:1")
