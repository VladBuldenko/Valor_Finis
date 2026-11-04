"""Approved-targets file: location, permissions and strict shape."""

import json

import pytest

from staging_ops import target_config
from staging_ops.errors import StagingRefused
from staging_ops.target_config import load_approved_targets, parse_approved_targets

from . import helpers as h


def code_of(callable_):
    with pytest.raises(StagingRefused) as caught:
        callable_()

    return caught.value.code


class TestFile:
    def test_loads_a_private_file_outside_the_repository(self, tmp_path):
        loaded = load_approved_targets(h.write_approved_file(tmp_path))

        assert loaded.staging[0].staging_id == "STG-1" and loaded.denylist.database_hosts == (h.PRODUCTION_HOST,)

    def test_missing_file(self, tmp_path):
        assert code_of(lambda: load_approved_targets(str(tmp_path / "absent.json"))) == "CONFIG_MISSING"

    def test_a_file_inside_the_repository_is_refused(self):
        inside = target_config.REPOSITORY_ROOT / "services" / "api" / "alembic.ini"

        assert code_of(lambda: load_approved_targets(str(inside))) == "CONFIG_LOCATION"

    @pytest.mark.parametrize("mode", [0o666, 0o662, 0o620])
    def test_group_or_world_writable_file_is_refused(self, tmp_path, mode):
        assert code_of(lambda: load_approved_targets(h.write_approved_file(tmp_path, mode=mode))) == "CONFIG_PERMISSIONS"

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        path.chmod(0o600)

        assert code_of(lambda: load_approved_targets(str(path))) == "CONFIG_MALFORMED"

    def test_a_directory_is_not_a_file(self, tmp_path):
        assert code_of(lambda: load_approved_targets(str(tmp_path))) in {"CONFIG_MALFORMED", "CONFIG_PERMISSIONS"}


class TestShape:
    def mutated(self, change):
        document = h.approved_document()
        change(document)

        return lambda: parse_approved_targets(document)

    @pytest.mark.parametrize(
        "change",
        [
            lambda d: d.update(extra=1),
            lambda d: d.pop("production_denylist"),
            lambda d: d.update(schema_version=2),
            lambda d: d.update(schema_version=True),
            lambda d: d["staging"][0].update(unknown="x"),
            lambda d: d["staging"][0].pop("approved_by"),
            lambda d: d["staging"][0].update(approved_by=" "),
            lambda d: d["staging"][0].update(approved_on="soon"),
            lambda d: d["staging"][0].update(id="stg-1"),
            lambda d: d["staging"][0]["database"].update(port="5432"),
            lambda d: d["staging"][0]["database"].update(port=70000),
            lambda d: d["staging"][0]["database"].update(oid=0),
            lambda d: d["staging"][0]["database"].update(oid=True),
            lambda d: d["staging"][0]["database"].update(name="valor"),
            lambda d: d["staging"][0]["database"].update(name="_staging"),
            lambda d: d["staging"][0]["database"].update(name="Valor_Staging"),
            lambda d: d["staging"][0]["database"].update(host="*.example.test"),
            lambda d: d["staging"][0]["database"].update(host="host with space"),
            lambda d: d["staging"][0].update(supabase_project_ref="Short"),
            lambda d: d["production_denylist"].update(recorded_by=""),
            lambda d: d["production_denylist"].update(recorded_on="2026-13-40"),
            lambda d: d["production_denylist"].update(database_hosts="prod-db.example.test"),
            lambda d: d["production_denylist"].update(supabase_project_refs=["BAD"]),
        ],
    )
    def test_malformed_documents_are_refused(self, change):
        assert code_of(self.mutated(change)) == "CONFIG_MALFORMED"

    def test_duplicate_ids_and_databases_are_contradictory(self):
        def duplicate_id(d):
            d["staging"].append(json.loads(json.dumps(d["staging"][0])))

        assert code_of(self.mutated(duplicate_id)) == "CONFIG_CONTRADICTORY"

    @pytest.mark.parametrize(
        "change",
        [
            lambda d: d["production_denylist"]["supabase_project_refs"].append(h.STAGING_REF),
            lambda d: d["production_denylist"]["database_names"].append(h.DATABASE),
            lambda d: d["production_denylist"]["database_hosts"].append("example.test"),
        ],
    )
    def test_overlap_with_the_denylist_is_contradictory(self, change):
        assert code_of(self.mutated(change)) == "CONFIG_CONTRADICTORY"


class TestDocumentedExample:
    def test_the_example_in_the_docs_is_valid_and_obviously_fake(self):
        path = target_config.REPOSITORY_ROOT / "docs/operations/staging/approved-targets.example.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        loaded = parse_approved_targets(document)

        assert loaded.staging[0].host.endswith(".invalid")
        assert all(host.endswith(".invalid") for host in loaded.denylist.database_hosts)
        assert document["staging"][0]["approved_on"] == "2000-01-01"
