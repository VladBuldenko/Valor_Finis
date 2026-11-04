"""Seed: authorization gate, deterministic scenario definitions, schema alignment."""

import subprocess
import sys
import uuid
from datetime import date

import pytest

from staging_ops.errors import StagingRefused
from staging_ops.seed import parse_users, seed
from staging_ops.seed_scenarios import ACTORS, BASE_CURRENCY, MARKER_PREFIX, SCENARIOS, build_scenarios, marker_name, request_id

from . import helpers as h

AS_OF = date(2026, 11, 20)
USERS = {"QA-A": "11111111-1111-4111-8111-111111111111", "QA-B": "22222222-2222-4222-8222-222222222222"}


def run_seed(ops, environ=None, flag="staging", users=None, approved=None):
    return seed(flag, "STG-1", environ if environ is not None else h.good_environ(), approved or h.approved(), ops.as_operations(), USERS if users is None else users, AS_OF, None, say=lambda _t: None)


class TestAuthorizationGate:
    def test_a_seed_for_an_unauthorized_target_never_opens_a_session(self):
        for kwargs in (
            dict(flag=None),
            dict(flag="production"),
            dict(environ=h.good_environ(DATABASE_URL=h.database_url(host="other-db.example.test"))),
            dict(environ=h.good_environ(DATABASE_URL=h.database_url(host=h.PRODUCTION_HOST))),
            dict(environ=h.good_environ(SUPABASE_URL=f"https://{h.PRODUCTION_REF}.supabase.co")),
            dict(approved=h.approved(lambda d: d["production_denylist"].update(supabase_project_refs=[]))),
        ):
            ops = h.FakeOps()

            with pytest.raises(StagingRefused):
                run_seed(ops, **kwargs)

            assert ops.sessions == 0 and ops.mutations == 0, kwargs

    def test_a_connected_database_that_differs_never_opens_a_session(self):
        ops = h.FakeOps(probes=[h.facts(database="valor_other_staging")])

        with pytest.raises(StagingRefused):
            run_seed(ops)

        assert ops.sessions == 0

    def test_identity_that_changes_before_the_seed_never_opens_a_session(self):
        ops = h.FakeOps(probes=[h.facts(), h.facts(postmaster_start="1700009999.0")])

        with pytest.raises(StagingRefused) as caught:
            run_seed(ops)

        assert caught.value.code == "IDENTITY_CHANGED" and ops.sessions == 0

    def test_invalid_user_mapping_is_refused_before_a_session(self):
        for users in ({}, {"QA-A": USERS["QA-A"]}, {**USERS, "QA-C": USERS["QA-A"]}, {"QA-A": "x", "QA-B": USERS["QA-B"]}, {"QA-A": USERS["QA-A"], "QA-B": USERS["QA-A"]}):
            ops = h.FakeOps()

            with pytest.raises(StagingRefused) as caught:
                run_seed(ops, users=users)

            assert caught.value.code == "USERS_INVALID" and ops.sessions == 0

    def test_parse_users_accepts_two_distinct_uuids(self):
        assert parse_users(USERS)["QA-A"] == uuid.UUID(USERS["QA-A"])

    def test_importing_the_seed_does_not_load_app_settings(self):
        # The CLI must be able to disable dotenv loading before app settings are imported.
        code = "import sys, staging_ops.seed, staging_ops.cli; assert 'app.core.app_config' not in sys.modules"
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr


class TestSeedSerialization:
    def test_the_lock_is_taken_before_any_session_and_released_when_the_run_stops(self):
        ops = h.FakeOps()

        with pytest.raises(StagingRefused):
            run_seed(ops)  # the fake session factory raises, ending the run

        assert ops.calls.index("seed_lock") < ops.calls.index("open_session")
        assert ops.lock_entered == 1 and ops.lock_released == 1

    def test_a_competing_seed_is_refused_before_a_session_and_reported_unchanged(self):
        ops = h.FakeOps(lock_busy=True)

        with pytest.raises(StagingRefused) as caught:
            run_seed(ops)

        assert caught.value.code == "LOCK_BUSY" and not caught.value.mutated
        assert ops.sessions == 0 and ops.mutations == 0


class TestScenarioDefinitions:
    def test_identical_input_gives_identical_output(self):
        assert build_scenarios(AS_OF) == build_scenarios(AS_OF)

    def test_dates_derive_from_as_of_only(self):
        first = build_scenarios(date(2026, 11, 20))
        second = build_scenarios(date(2026, 12, 5))

        assert [s.kind for s in first["QA-A"]] == [s.kind for s in second["QA-A"]]
        assert [s.key for s in first["QA-A"]] == [s.key for s in second["QA-A"]]
        assert first != second

    def test_scenario_identifiers_are_stable_and_all_covered(self):
        used = {step.scenario for actor in ACTORS for step in build_scenarios(AS_OF)[actor]}

        assert used == set(SCENARIOS)
        assert all(identifier.startswith("QA1-S") for identifier in SCENARIOS)

    def test_step_keys_are_unique_and_references_point_backwards(self):
        for actor, steps in build_scenarios(AS_OF).items():
            seen = set()

            for step in steps:
                assert step.key not in seen, (actor, step.key)
                text = repr(step.payload)

                for earlier in [token.split("'")[0] for token in text.split("$ref:")[1:]]:
                    assert earlier in seen, (actor, step.key, earlier)

                seen.add(step.key)

    def test_the_seed_needs_no_exchange_rate_lookup(self):
        for steps in build_scenarios(AS_OF).values():
            for step in steps:
                if step.kind in ("income", "expense"):
                    assert step.payload["currency"] == BASE_CURRENCY

    def test_required_coverage(self):
        steps = build_scenarios(AS_OF)["QA-A"]
        kinds = {step.kind for step in steps}
        currencies = {step.payload["currency"] for step in steps if step.kind == "account"}
        rules = [step.payload for step in steps if step.kind == "rule"]

        assert {"account", "goal", "budget", "income", "expense", "reservation", "rule", "drain", "alerts", "category"} <= kinds
        assert len(currencies) >= 2
        assert {"AUTO", "CONFIRM"} <= {rule.get("execution_mode") for rule in rules}
        assert {"MINIMUM_UNALLOCATED_FLOOR", "BUDGET_ALERT"} <= {rule["rule_type"] for rule in rules}

    def test_the_rules_are_enabled_before_the_first_income(self):
        keys = [step.key for step in build_scenarios(AS_OF)["QA-A"]]

        assert max(keys.index(k) for k in keys if k.startswith("rule-")) < keys.index("income-salary")

    def test_the_two_actors_have_overlapping_names_but_separate_data(self):
        a, b = build_scenarios(AS_OF)["QA-A"], build_scenarios(AS_OF)["QA-B"]

        assert next(s for s in a if s.key == "cat").payload["name"] == next(s for s in b if s.key == "cat").payload["name"]
        assert {s.payload.get("name") for s in a if s.kind == "account"}.isdisjoint({s.payload.get("name") for s in b if s.kind == "account"})

    def test_request_ids_are_stable_and_unique(self):
        assert request_id("QA-A", "reserve-usd") == request_id("QA-A", "reserve-usd")
        assert request_id("QA-A", "reserve-usd") != request_id("QA-B", "reserve-usd")
        # Pinned: changing the namespace would let a re-seed create a second reservation.
        assert request_id("QA-A", "reserve-usd") == "699601b1-313b-55e8-abdc-4220a14e8524"

    def test_marker_name(self):
        assert marker_name("STG-1") == MARKER_PREFIX + "STG-1" == "QA-SEED-STG-1"


class TestPayloadsMatchTheBackendSchemas:
    def test_every_payload_validates_against_the_domain_schemas(self):
        from app.modules.accounts.account_schemas import AccountCreate
        from app.modules.budgets.budget_schemas import BudgetCreate
        from app.modules.categories.schemas import CategoryCreate
        from app.modules.expenses.expenses_schemas import ExpenseCreate
        from app.modules.financial_rules.financial_rule_schemas import financial_rule_create_adapter
        from app.modules.goals.goal_schemas import GoalCreate
        from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate
        from app.modules.income.income_schemas import IncomeCreate
        from staging_ops.seed import _resolve

        models = {"category": CategoryCreate, "account": AccountCreate, "goal": GoalCreate, "budget": BudgetCreate, "income": IncomeCreate, "expense": ExpenseCreate}

        for actor, steps in build_scenarios(AS_OF).items():
            ids = {step.key: uuid.uuid4() for step in steps}

            for step in steps:
                payload = _resolve(step.payload, ids)

                if step.kind in models:
                    models[step.kind].model_validate(payload)
                elif step.kind == "rule":
                    financial_rule_create_adapter.validate_python(payload)
                elif step.kind == "reservation":
                    payload.pop("goal")
                    GoalTransactionCreate.model_validate(payload)
