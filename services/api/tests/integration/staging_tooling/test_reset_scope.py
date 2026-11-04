"""
Reset scope against a REAL disposable PostgreSQL.

Invariant under test: a staging reset never modifies or drops an object outside
schema `public`. Each scenario builds an object in schema `ext` (standing in for
Supabase's own schemas) that depends on a `public` application object, then
proves (a) the preflight reports it, (b) the destroy transaction refuses and
rolls back, and (c) with the preflight disabled the remaining layers
(RESTRICT and the out-of-scope fingerprint) still stop the reset. In every case
an INDEPENDENT oracle (not the production fingerprint) compares the complete
definition and rows of everything in `ext` before and after: if anything in
`ext` differs, the test fails and the operation is unsafe.

These are real database tests; nothing here is mocked except where a test says
it disables one named layer to prove the next one holds.
"""

import contextlib
import threading

import psycopg2
import pytest

from staging_ops import binding, database, reset_scope
from staging_ops.bootstrap import bootstrap
from staging_ops.errors import StagingRefused
from staging_ops.reset import reset

from .helpers import SpyOperations, approved_for, environ_for, execute, fetch, verified_target

WORLD = (
    "CREATE SCHEMA ext",
    "CREATE TYPE public.vf_kind AS ENUM ('a', 'b')",
    "CREATE FUNCTION public.vf_ok() RETURNS boolean LANGUAGE sql AS 'select true'",
    "CREATE FUNCTION public.vf_touch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
    "CREATE TABLE public.vf_accounts (id int PRIMARY KEY, kind public.vf_kind, n int, m int)",
    "INSERT INTO public.vf_accounts VALUES (1, 'a', 1, 1), (2, 'b', 2, 2)",
    "CREATE TABLE public.vf_part (id int) PARTITION BY RANGE (id)",
    "CREATE TABLE ext.keep (id int PRIMARY KEY, label text)",
    "INSERT INTO ext.keep VALUES (1, 'one'), (2, 'two')",
)

# name -> (statements creating the external dependent, whether PostgreSQL's own
# RESTRICT already blocks it; False means an AUTOMATIC dependency that only the
# preflight and the fingerprint can stop).
EXTERNAL_DEPENDENTS = {
    "view": (("CREATE VIEW ext.v AS SELECT id, n FROM public.vf_accounts",), True),
    "view-on-function": (("CREATE VIEW ext.vf AS SELECT public.vf_ok() AS ok",), True),
    "materialized-view": (("CREATE MATERIALIZED VIEW ext.mv AS SELECT id FROM public.vf_accounts",), True),
    "foreign-key": (("CREATE TABLE ext.child (id int PRIMARY KEY, account_id int REFERENCES public.vf_accounts(id))", "INSERT INTO ext.child VALUES (1, 1)"), True),
    "trigger": (("CREATE TABLE ext.t (id int)", "CREATE TRIGGER trg BEFORE INSERT ON ext.t FOR EACH ROW EXECUTE FUNCTION public.vf_touch()"), True),
    "policy": (("CREATE TABLE ext.p (id int)", "ALTER TABLE ext.p ENABLE ROW LEVEL SECURITY", "CREATE POLICY pol ON ext.p USING (public.vf_ok())"), True),
    "column-typed-by-public-enum": (("CREATE TABLE ext.e (id int, k public.vf_kind)", "INSERT INTO ext.e VALUES (1, 'a')"), True),
    "column-default-calls-public-function": (("CREATE TABLE ext.d (id int DEFAULT (CASE WHEN public.vf_ok() THEN 1 ELSE 2 END))",), True),
    "check-constraint-calls-public-function": (("CREATE TABLE ext.c (id int CHECK (public.vf_ok()))",), True),
    "function-argument-typed-by-public-enum": (("CREATE FUNCTION ext.f(k public.vf_kind) RETURNS int LANGUAGE sql AS 'select 1'",), True),
    "function-returning-public-rowtype": (("CREATE FUNCTION ext.g() RETURNS SETOF public.vf_accounts LANGUAGE sql AS 'select * from public.vf_accounts'",), True),
    "domain-over-public-enum": (("CREATE DOMAIN ext.dom AS public.vf_kind",), True),
    "table-inheriting-a-public-table": (("CREATE TABLE ext.inh () INHERITS (public.vf_accounts)",), True),
    "operator-using-a-public-function": (("CREATE FUNCTION public.vf_eq(int, int) RETURNS boolean LANGUAGE sql AS 'select $1 = $2'", "CREATE OPERATOR ext.=== (LEFTARG = int, RIGHTARG = int, FUNCTION = public.vf_eq)"), True),
    "partition-of-a-public-table": (("CREATE TABLE ext.part_child PARTITION OF public.vf_part FOR VALUES FROM (0) TO (10)",), False),
    "extended-statistics-on-a-public-table": (("CREATE STATISTICS ext.st ON n, m FROM public.vf_accounts",), False),
}


def build_world(cluster, external=()):
    name, oid = cluster.create_database()
    execute(cluster, name, *WORLD, *external)
    environ, verified = verified_target(cluster, name, oid)

    return name, oid, verified


def oracle(cluster, name):
    """Complete definitions and rows of everything in `ext`, read independently of the production code."""

    queries = (
        "SELECT c.relname, c.relkind, (SELECT string_agg(a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull || ':' || a.attisdropped, ',' ORDER BY a.attnum) FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0) FROM pg_class c WHERE c.relnamespace = 'ext'::regnamespace ORDER BY 1",
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = 'ext'::regnamespace ORDER BY 1, 2",
        "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace = 'ext'::regnamespace) ORDER BY 1, 2",
        "SELECT tablename, policyname, qual FROM pg_policies WHERE schemaname = 'ext' ORDER BY 1, 2",
        "SELECT viewname, definition FROM pg_views WHERE schemaname = 'ext' ORDER BY 1",
        "SELECT matviewname, definition FROM pg_matviews WHERE schemaname = 'ext' ORDER BY 1",
        "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.pronamespace = 'ext'::regnamespace ORDER BY 1",
        "SELECT typname, typtype FROM pg_type WHERE typnamespace = 'ext'::regnamespace ORDER BY 1",
        "SELECT inhrelid::regclass::text, inhparent::regclass::text FROM pg_inherits WHERE inhrelid IN (SELECT oid FROM pg_class WHERE relnamespace = 'ext'::regnamespace) ORDER BY 1",
        "SELECT stxname, stxrelid::regclass::text FROM pg_statistic_ext WHERE stxnamespace = 'ext'::regnamespace ORDER BY 1",
        "SELECT oprname, oprcode::text FROM pg_operator WHERE oprnamespace = 'ext'::regnamespace ORDER BY 1",
    )
    state = {query: fetch(cluster, name, query) for query in queries}

    for relation, kind in fetch(cluster, name, "SELECT relname, relkind FROM pg_class WHERE relnamespace = 'ext'::regnamespace AND relkind IN ('r', 'p', 'm', 'v') ORDER BY 1"):
        state[f"rows:{relation}"] = fetch(cluster, name, f'SELECT to_jsonb(t)::text FROM ext."{relation}" t ORDER BY 1')

    return state


def public_state(cluster, name):
    relations = fetch(cluster, name, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p', 'v', 'm', 'S') ORDER BY 1")
    rows = fetch(cluster, name, "SELECT id, kind::text FROM public.vf_accounts ORDER BY 1") if ("vf_accounts",) in relations else None

    return relations, rows


class TestEveryExternalDependencyKindIsRefusedAndNothingMoves:
    @pytest.mark.parametrize("scenario", sorted(EXTERNAL_DEPENDENTS))
    def test_preflight_and_destroy_refuse_and_leave_ext_untouched(self, local_cluster, scenario):
        statements, _restrict_blocks = EXTERNAL_DEPENDENTS[scenario]
        name, _oid, verified = build_world(local_cluster, statements)
        ext_before, public_before = oracle(local_cluster, name), public_state(local_cluster, name)

        found = database.external_dependents(verified)
        assert found, f"{scenario}: the preflight must report the external dependent"

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "EXTERNAL_DEPENDENCIES"
        assert oracle(local_cluster, name) == ext_before, f"{scenario}: an object outside public changed"
        assert public_state(local_cluster, name) == public_before, f"{scenario}: the refusal must keep the application objects too"

    @pytest.mark.parametrize("scenario", sorted(EXTERNAL_DEPENDENTS))
    def test_with_the_preflight_disabled_restrict_and_the_fingerprint_still_hold(self, local_cluster, monkeypatch, scenario):
        statements, restrict_blocks = EXTERNAL_DEPENDENTS[scenario]
        name, _oid, verified = build_world(local_cluster, statements)
        ext_before, public_before = oracle(local_cluster, name), public_state(local_cluster, name)
        # Simulates a dependency kind (or a race) the preflight query did not see.
        monkeypatch.setattr(reset_scope, "external_dependents", lambda _connection: [])

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        # RESTRICT stops the ordinary dependencies; the automatic ones (partitions,
        # extended statistics) are dropped by PostgreSQL even under RESTRICT, so
        # only the fingerprint gate can refuse them.
        assert caught.value.code == ("RESET_BLOCKED" if restrict_blocks else "EXTERNAL_OBJECT_CHANGED"), caught.value
        assert oracle(local_cluster, name) == ext_before, f"{scenario}: an object outside public changed"
        assert public_state(local_cluster, name) == public_before

    def test_without_the_fingerprint_gate_an_automatic_dependent_would_be_destroyed(self, local_cluster, monkeypatch):
        """Negative control: proves the fingerprint gate is what protects the automatic dependencies."""

        statements, _ = EXTERNAL_DEPENDENTS["partition-of-a-public-table"]
        name, _oid, verified = build_world(local_cluster, statements)
        monkeypatch.setattr(reset_scope, "external_dependents", lambda _connection: [])
        monkeypatch.setattr(reset_scope, "outside_fingerprint", lambda _connection: "constant")

        database.destroy_application_objects(verified)

        assert fetch(local_cluster, name, "SELECT to_regclass('ext.part_child') IS NULL") == [(True,)], "the harness must be able to detect a real boundary crossing"


class TestSuccessfulResetInsideTheScope:
    def test_only_authorized_objects_are_removed_and_ext_is_untouched(self, local_cluster):
        name, _oid, verified = build_world(local_cluster)
        ext_before = oracle(local_cluster, name)

        dropped = database.destroy_application_objects(verified)

        assert dropped >= 5
        assert fetch(local_cluster, name, binding.UNEXPECTED_OBJECTS_SQL) == [(0,)]
        assert oracle(local_cluster, name) == ext_before

    def test_outbound_references_are_removed_with_the_application_object_and_the_target_is_unchanged(self, local_cluster):
        name, _oid, verified = build_world(
            local_cluster,
            (
                "CREATE TABLE public.out_ref (id int REFERENCES ext.keep(id))",
                "INSERT INTO public.out_ref VALUES (1)",
                "CREATE VIEW public.out_view AS SELECT * FROM ext.keep",
            ),
        )
        ext_before = oracle(local_cluster, name)

        database.destroy_application_objects(verified)

        assert oracle(local_cluster, name) == ext_before, "the referenced table must keep its definition, constraints and rows"
        assert fetch(local_cluster, name, binding.UNEXPECTED_OBJECTS_SQL) == [(0,)]

    def test_internal_dependencies_of_every_kind_resolve_without_cascade(self, local_cluster):
        name, _oid, verified = build_world(
            local_cluster,
            (
                # mutual foreign keys, resolved by dropping both tables in one statement
                "CREATE TABLE public.m1 (id int PRIMARY KEY, m2_id int)",
                "CREATE TABLE public.m2 (id int PRIMARY KEY, m1_id int REFERENCES public.m1(id))",
                "ALTER TABLE public.m1 ADD FOREIGN KEY (m2_id) REFERENCES public.m2(id)",
                # view on view, materialized view, trigger on a public table calling a public function
                "CREATE VIEW public.va AS SELECT id FROM public.vf_accounts",
                "CREATE VIEW public.vb AS SELECT id FROM public.va",
                "CREATE MATERIALIZED VIEW public.mva AS SELECT id FROM public.vb",
                "CREATE TRIGGER vf_trg BEFORE INSERT ON public.m1 FOR EACH ROW EXECUTE FUNCTION public.vf_touch()",
                # defaults from a function and a standalone sequence, identity, serial
                "CREATE SEQUENCE public.vf_seq",
                "CREATE TABLE public.dflt (id int DEFAULT nextval('public.vf_seq'), ok boolean DEFAULT public.vf_ok(), ident int GENERATED ALWAYS AS IDENTITY, s serial)",
                # function returning a public table's rowtype (function depends on table)
                "CREATE FUNCTION public.vf_rows() RETURNS SETOF public.vf_accounts LANGUAGE sql AS 'select * from public.vf_accounts'",
                # types
                "CREATE TYPE public.vf_comp AS (x int, y text)",
                "CREATE TYPE public.vf_range AS RANGE (subtype = int4)",
                "CREATE DOMAIN public.vf_dom AS public.vf_kind",
                "CREATE FUNCTION public.vf_with_type(k public.vf_kind, c public.vf_comp) RETURNS public.vf_dom LANGUAGE sql AS 'select null::public.vf_dom'",
                "CREATE PROCEDURE public.vf_proc() LANGUAGE sql AS 'select 1'",
                "CREATE AGGREGATE public.vf_agg(int) (SFUNC = int4pl, STYPE = int, INITCOND = '0')",
                "CREATE AGGREGATE public.vf_count_all(*) (SFUNC = int8inc, STYPE = int8, INITCOND = '0')",
                # policy and index, partitions and in-schema inheritance
                "ALTER TABLE public.m1 ENABLE ROW LEVEL SECURITY",
                "CREATE POLICY vf_pol ON public.m1 USING (public.vf_ok())",
                "CREATE INDEX vf_idx ON public.vf_accounts (n)",
                "CREATE TABLE public.vf_part_a PARTITION OF public.vf_part FOR VALUES FROM (0) TO (10)",
                "CREATE TABLE public.inh_child () INHERITS (public.vf_accounts)",
                # awkward names
                'CREATE TABLE public."Odd Name" ("Col" int)',
                'CREATE TABLE public."50%_off" (id int)',
                'CREATE TABLE public."colon:name" (id int)',
                'CREATE TABLE public."quote""d" (id int)',
            ),
        )
        ext_before = oracle(local_cluster, name)

        database.destroy_application_objects(verified)

        assert fetch(local_cluster, name, binding.UNEXPECTED_OBJECTS_SQL) == [(0,)]
        assert oracle(local_cluster, name) == ext_before

    def test_a_public_partition_of_an_external_parent_is_refused_because_it_would_change_the_parent(self, local_cluster):
        name, _oid, verified = build_world(
            local_cluster,
            (
                "CREATE TABLE ext.pp (id int) PARTITION BY RANGE (id)",
                "CREATE TABLE public.pp_child PARTITION OF ext.pp FOR VALUES FROM (0) TO (10)",
                "INSERT INTO ext.pp VALUES (5)",
            ),
        )
        ext_before, public_before = oracle(local_cluster, name), public_state(local_cluster, name)

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        # Not an inbound dependent, so only the fingerprint can see that dropping the child edits the parent.
        assert caught.value.code == "EXTERNAL_OBJECT_CHANGED"
        assert oracle(local_cluster, name) == ext_before and public_state(local_cluster, name) == public_before
        assert fetch(local_cluster, name, "SELECT id FROM ext.pp") == [(5,)]

    def test_a_dependency_cycle_across_kinds_is_blocked_not_cascaded(self, local_cluster):
        # The column default needs the function; the function's return type is the table's rowtype.
        name, _oid, verified = build_world(
            local_cluster,
            (
                "CREATE TABLE public.cyc (id int)",
                "CREATE FUNCTION public.cyc_fn() RETURNS public.cyc LANGUAGE sql AS 'select null::public.cyc'",
                "ALTER TABLE public.cyc ADD COLUMN d boolean DEFAULT (public.cyc_fn() IS NULL)",
            ),
        )
        before = (public_state(local_cluster, name), oracle(local_cluster, name))

        with pytest.raises(StagingRefused) as caught:
            database.destroy_application_objects(verified)

        assert caught.value.code == "RESET_BLOCKED"
        assert (public_state(local_cluster, name), oracle(local_cluster, name)) == before

    def test_extension_owned_objects_in_public_survive(self, local_cluster):
        name, oid = local_cluster.create_database()

        try:
            execute(local_cluster, name, "CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public")
        except psycopg2.Error:
            pytest.skip("NOT RUN: the contrib extension pg_trgm is not installed in this PostgreSQL")

        execute(local_cluster, name, "CREATE TABLE public.app_table (id int)")
        _environ, verified = verified_target(local_cluster, name, oid)

        assert database.external_dependents(verified) == []
        database.destroy_application_objects(verified)

        assert fetch(local_cluster, name, "SELECT count(*) FROM pg_proc WHERE proname = 'similarity' AND pronamespace = 'public'::regnamespace")[0][0] >= 1
        assert fetch(local_cluster, name, "SELECT to_regclass('public.app_table') IS NULL") == [(True,)]

    def test_the_real_application_schema_has_no_external_dependents_and_resets_cleanly(self, local_cluster):
        name, oid = local_cluster.create_database()
        environ, approved, spy = environ_for(local_cluster, name), approved_for(local_cluster, name, oid), SpyOperations()
        bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, lambda _t: None)
        _environ, verified = verified_target(local_cluster, name, oid)
        execute(local_cluster, name, "CREATE SCHEMA ext", "CREATE TABLE ext.keep (id int)", "INSERT INTO ext.keep VALUES (7)")
        ext_before = oracle(local_cluster, name)

        assert database.external_dependents(verified) == [], "a false positive here would make every real reset refuse"
        assert database.destroy_application_objects(verified) > 10
        assert fetch(local_cluster, name, binding.UNEXPECTED_OBJECTS_SQL) == [(0,)]
        assert oracle(local_cluster, name) == ext_before


class TestRaceWindows:
    def test_a_dependent_created_after_the_preflight_is_refused_by_the_destroy_transaction(self, local_cluster):
        name, oid = local_cluster.create_database()
        environ, approved, spy = environ_for(local_cluster, name), approved_for(local_cluster, name, oid), SpyOperations()
        bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, lambda _t: None)
        execute(local_cluster, name, "CREATE SCHEMA ext")
        operations = spy.operations()
        real_describe = operations.describe

        def describe_then_race(verified):
            # Runs after the preflight and before the destroy transaction.
            execute(local_cluster, name, "CREATE VIEW ext.late AS SELECT id FROM public.accounts")

            return real_describe(verified)

        operations.describe = describe_then_race
        phrase = f"STG-1/{name}@{local_cluster.host}:{local_cluster.port}"

        with pytest.raises(StagingRefused) as caught:
            reset("staging", "STG-1", environ, approved, operations, lambda _p: phrase, None, lambda _t: None)

        assert caught.value.code == "EXTERNAL_DEPENDENCIES" and not caught.value.mutated
        assert fetch(local_cluster, name, "SELECT to_regclass('ext.late') IS NOT NULL AND to_regclass('public.accounts') IS NOT NULL") == [(True,)]
        assert spy.alembic_runs == 1, "only the bootstrap ran; the failed reset must not rebuild"

    def test_ddl_that_would_add_a_dependent_waits_for_the_destroy_transaction(self, local_cluster, monkeypatch):
        name, _oid, verified = build_world(local_cluster)
        reached, proceed = threading.Event(), threading.Event()
        real_fingerprint = reset_scope.outside_fingerprint
        calls = []

        def paused_fingerprint(connection):
            calls.append(1)

            if len(calls) == 1:
                reached.set()
                assert proceed.wait(30)

            return real_fingerprint(connection)

        monkeypatch.setattr(reset_scope, "outside_fingerprint", paused_fingerprint)
        outcome = {}

        def run():
            try:
                outcome["dropped"] = database.destroy_application_objects(verified)
            except BaseException as error:  # noqa: BLE001 - reported to the main thread
                outcome["error"] = error

        worker = threading.Thread(target=run)
        worker.start()

        try:
            assert reached.wait(30), "the destroy transaction never reached the checkpoint"

            for statement in (
                "CREATE VIEW ext.late AS SELECT id FROM public.vf_accounts",
                "CREATE TABLE ext.late_fk (id int REFERENCES public.vf_accounts(id))",
                "CREATE STATISTICS ext.late_st ON n, m FROM public.vf_accounts",
            ):
                with contextlib.closing(local_cluster.connect(name)) as connection, connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '700ms'")

                    with pytest.raises(psycopg2.errors.LockNotAvailable):
                        cursor.execute(statement)
        finally:
            proceed.set()
            worker.join(60)

        assert "error" not in outcome, outcome.get("error")
        assert fetch(local_cluster, name, "SELECT to_regclass('ext.late') IS NULL AND to_regclass('ext.late_fk') IS NULL") == [(True,)]
        assert fetch(local_cluster, name, binding.UNEXPECTED_OBJECTS_SQL) == [(0,)]

    def test_an_uncommitted_dependent_in_another_session_makes_the_reset_fail_closed(self, local_cluster, monkeypatch):
        name, _oid, verified = build_world(local_cluster)
        monkeypatch.setattr(database, "MUTATION_OPTIONS", "-c lock_timeout=500 -c statement_timeout=20000")
        racer = local_cluster.connect(name)
        racer.autocommit = False

        try:
            with racer.cursor() as cursor:
                cursor.execute("CREATE VIEW ext.racing AS SELECT id FROM public.vf_accounts")

            with pytest.raises(StagingRefused) as caught:
                database.destroy_application_objects(verified)

            assert caught.value.code == "RESET_FAILED"
            racer.commit()
        finally:
            racer.close()

        assert fetch(local_cluster, name, "SELECT to_regclass('ext.racing') IS NOT NULL AND to_regclass('public.vf_accounts') IS NOT NULL") == [(True,)]
        assert [row[0] for row in fetch(local_cluster, name, "SELECT id FROM public.vf_accounts ORDER BY 1")] == [1, 2]
