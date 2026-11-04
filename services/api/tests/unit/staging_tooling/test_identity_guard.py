"""Negative and positive tests for the staging identity guard (VF-QA-1)."""

import pytest

from staging_ops.errors import StagingRefused
from staging_ops.identity import (
    ConfiguredTarget,
    assert_same_identity,
    verify_configuration,
    verify_facts,
)
from staging_ops.target_config import ApprovedTargets, StagingEntry
from . import helpers as h


def verify(environ=None, flag="staging", staging="STG-1", approved=None, **kwargs):
    return verify_configuration(flag, staging, environ if environ is not None else h.good_environ(), approved or h.approved(), **kwargs)


def refused(code, **kwargs):
    with pytest.raises(StagingRefused) as caught:
        verify(**kwargs)

    assert caught.value.code == code, caught.value
    return caught.value


class TestPositive:
    def test_accepts_the_exact_approved_target(self):
        target = verify()

        assert (target.staging_id, target.host, target.port, target.database, target.oid) == ("STG-1", h.STAGING_HOST, 5432, h.DATABASE, h.OID)
        assert target.confirmation_phrase() == f"STG-1/{h.DATABASE}@{h.STAGING_HOST}:5432"

    def test_loopback_may_use_a_plain_connection(self):
        approved = h.approved(lambda d: d["staging"][0]["database"].update(host="127.0.0.1"))

        assert verify(h.good_environ(DATABASE_URL=h.database_url(host="127.0.0.1", query="")), approved=approved).host == "127.0.0.1"

    def test_repr_never_contains_the_url_or_password(self):
        assert h.PASSWORD not in repr(verify()) and "svc_user" not in repr(verify())


class TestEnvironmentFlag:
    def test_missing_flag(self):
        refused("ENV_FLAG_MISSING", flag=None)

    @pytest.mark.parametrize("flag", ["production", "prod", "Staging", "staging ", "", "test"])
    def test_wrong_flag(self, flag):
        refused("ENV_FLAG_WRONG", flag=flag)


class TestAllowlist:
    def test_unknown_staging_id(self):
        refused("STAGING_ID_UNKNOWN", staging="STG-9")
        refused("STAGING_ID_UNKNOWN", staging=None)

    def test_correct_suffix_but_wrong_host_is_refused(self):
        refused("TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="other-db.example.test")))

    def test_allowlisted_host_with_the_wrong_database_is_refused(self):
        refused("DATABASE_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(database="valor_other_staging")))
        refused("DATABASE_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(database="valor_production")))

    def test_wrong_port_is_refused(self):
        refused("TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(port=5433)))

    def test_host_comparison_is_exact_not_a_suffix_or_substring(self):
        refused("TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="evil-" + h.STAGING_HOST)))
        refused("TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="x." + h.STAGING_HOST)))

    def test_suffix_check_still_holds_if_an_entry_somehow_lacks_it(self):
        entry = StagingEntry("STG-1", h.STAGING_HOST, 5432, "valor_main", h.OID, h.STAGING_REF)
        unsafe = ApprovedTargets((entry,), h.approved().denylist)

        refused("DATABASE_SUFFIX", environ=h.good_environ(DATABASE_URL=h.database_url(database="valor_main")), approved=unsafe)


class TestProductionDenylist:
    def test_production_host_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(host=h.PRODUCTION_HOST)))

    def test_subdomain_of_a_production_host_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(host="replica." + h.PRODUCTION_HOST)))

    def test_production_database_name_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(database="valor")))

    def test_production_supabase_project_in_the_url_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(SUPABASE_URL=f"https://{h.PRODUCTION_REF}.supabase.co"))

    def test_production_project_in_a_pooler_user_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(user="postgres." + h.PRODUCTION_REF)))

    def test_production_project_in_a_supabase_database_host_matches(self):
        refused("DENYLIST_HIT", environ=h.good_environ(DATABASE_URL=h.database_url(host=f"db.{h.PRODUCTION_REF}.supabase.co")))

    @pytest.mark.parametrize("field", ["database_hosts", "supabase_project_refs"])
    def test_an_empty_denylist_is_refused(self, field):
        approved = h.approved(lambda d: d["production_denylist"].update({field: []}))

        refused("DENYLIST_EMPTY", approved=approved)

    def test_a_staging_entry_that_overlaps_the_denylist_cannot_even_be_loaded(self):
        with pytest.raises(StagingRefused) as caught:
            h.approved(lambda d: d["production_denylist"]["database_hosts"].append(h.STAGING_HOST))

        assert caught.value.code == "CONFIG_CONTRADICTORY"


class TestSupabaseProject:
    def test_a_different_project_is_refused(self):
        refused("SUPABASE_PROJECT_MISMATCH", environ=h.good_environ(SUPABASE_URL="https://otherprojectrefabcdef.supabase.co"))

    def test_database_host_of_another_project_is_refused(self):
        refused("SUPABASE_PROJECT_MISMATCH", environ=h.good_environ(DATABASE_URL=h.database_url(host="db.otherprojectrefabcdef.supabase.co")), approved=h.approved(lambda d: d["staging"][0]["database"].update(host="db.otherprojectrefabcdef.supabase.co")))

    @pytest.mark.parametrize(
        "url",
        [
            "http://" + h.STAGING_REF + ".supabase.co",
            "https://" + h.STAGING_REF + ".supabase.co:8443",
            "https://user@" + h.STAGING_REF + ".supabase.co",
            "https://" + h.STAGING_REF + ".supabase.co/rest/v1",
            "https://" + h.STAGING_REF + ".example.test",
            "https://evil.test/" + h.STAGING_REF + ".supabase.co",
        ],
    )
    def test_malformed_or_foreign_supabase_urls_are_refused(self, url):
        refused("SUPABASE_URL_INVALID", environ=h.good_environ(SUPABASE_URL=url))


class TestContradictoryOrMissingConfiguration:
    @pytest.mark.parametrize("name", ["DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"])
    def test_missing_required_variable(self, name):
        refused("CONFIG_MISSING", environ=h.good_environ(**{name: None}))
        refused("CONFIG_MISSING", environ=h.good_environ(**{name: "  "}))

    @pytest.mark.parametrize("mode", [None, "", "development", "Development"])
    def test_auth_mode_must_be_supabase(self, mode):
        refused("AUTH_MODE_CONTRADICTORY", environ=h.good_environ(AUTH_MODE=mode))

    @pytest.mark.parametrize("name", ["PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGSSLMODE"])
    def test_libpq_overrides_are_refused(self, name):
        refused("CONFIG_OVERRIDE", environ=h.good_environ(**{name: "x"}))

    @pytest.mark.parametrize(
        "query",
        ["host=prod-db.example.test", "hostaddr=192.0.2.11", "dbname=valor", "port=6000", "service=prod", "options=-csearch_path%3Dx", "sslmode=require&host=x"],
    )
    def test_url_parameters_that_override_the_identity_are_refused(self, query):
        refused("CONFIG_MALFORMED", environ=h.good_environ(DATABASE_URL=h.database_url(query=query)))

    @pytest.mark.parametrize("url", ["not a url", "mysql://u:p@h/db", "postgresql:///valor_staging", f"postgresql://u:p@{h.STAGING_HOST},other.example.test/valor_staging?sslmode=require", f"postgresql://{h.STAGING_HOST}/valor_staging?sslmode=require"])
    def test_malformed_database_urls_are_refused(self, url):
        refused("CONFIG_MALFORMED", environ=h.good_environ(DATABASE_URL=url))

    def test_a_transaction_mode_pooler_is_refused(self):
        refused("POOLER_UNSUPPORTED", environ=h.good_environ(DATABASE_URL=h.database_url(port=6543)))

    @pytest.mark.parametrize("query", ["", "sslmode=disable", "sslmode=prefer", "sslmode=allow"])
    def test_remote_hosts_require_tls(self, query):
        refused("TLS_REQUIRED", environ=h.good_environ(DATABASE_URL=h.database_url(query=query)))

    def test_the_oid_must_be_pinned_for_mutations_but_not_for_identify(self):
        unpinned = h.approved(lambda d: d["staging"][0]["database"].pop("oid"))

        refused("OID_NOT_PINNED", approved=unpinned)
        assert verify(approved=unpinned, require_oid=False).oid is None

    def test_refusal_messages_never_contain_hosts_users_or_passwords(self):
        error = refused("TARGET_NOT_ALLOWLISTED", environ=h.good_environ(DATABASE_URL=h.database_url(host="other-db.example.test")))
        text = str(error)

        for secret in (h.PASSWORD, "svc_user", "other-db", h.STAGING_HOST, h.PUBLISHABLE_KEY):
            assert secret not in text


class TestConnectedIdentity:
    def target(self, **kwargs) -> ConfiguredTarget:
        return verify(**kwargs)

    def test_matching_facts_are_accepted(self):
        verified = verify_facts(self.target(), h.facts())

        assert (verified.oid, verified.postmaster_start) == (h.OID, h.POSTMASTER)
        assert verified.binding() == {"database": h.DATABASE, "oid": h.OID, "postmaster_start": h.POSTMASTER}

    def test_connected_database_differs_from_the_validated_target(self):
        with pytest.raises(StagingRefused) as caught:
            verify_facts(self.target(), h.facts(database="valor_other_staging"))

        assert caught.value.code == "CONNECTED_DATABASE_MISMATCH"

    def test_connected_database_without_the_suffix_is_refused_even_if_names_were_confused(self):
        # A name match alone is not enough, and a name without the suffix never passes.
        entry = StagingEntry("STG-1", h.STAGING_HOST, 5432, "valor_main", h.OID, h.STAGING_REF)
        configured = ConfiguredTarget("STG-1", h.STAGING_HOST, 5432, "valor_main", h.OID, h.STAGING_REF, "x")

        with pytest.raises(StagingRefused) as caught:
            verify_facts(configured, h.facts(database="valor_main"))

        assert caught.value.code == "DATABASE_SUFFIX" and entry

    def test_right_name_wrong_oid_is_a_different_database(self):
        with pytest.raises(StagingRefused) as caught:
            verify_facts(self.target(), h.facts(oid=h.OID + 1))

        assert caught.value.code == "CONNECTED_OID_MISMATCH"

    def test_a_standby_is_refused(self):
        with pytest.raises(StagingRefused) as caught:
            verify_facts(self.target(), h.facts(in_recovery=True))

        assert caught.value.code == "NOT_PRIMARY"

    @pytest.mark.parametrize("change", [dict(database="valor_other_staging"), dict(oid=1), dict(postmaster_start="1700000999.0"), dict(in_recovery=True)])
    def test_identity_that_changes_before_the_mutation_is_refused(self, change):
        verified = verify_facts(self.target(), h.facts())

        assert_same_identity(verified, h.facts())

        with pytest.raises(StagingRefused) as caught:
            assert_same_identity(verified, h.facts(**change))

        assert caught.value.code == "IDENTITY_CHANGED"
