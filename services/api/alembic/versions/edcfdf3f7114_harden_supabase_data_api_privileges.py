"""harden supabase data api privileges

Revision ID: edcfdf3f7114
Revises: 811506d8afd2
Create Date: 2026-09-24 10:49:55.950471

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'edcfdf3f7114'
down_revision: Union[str, Sequence[str], None] = '811506d8afd2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The exact, explicit set of application-owned public tables this
# migration governs (VF-SEC-01). Deliberately NOT "ALL TABLES IN SCHEMA
# public": this migration owns the security posture of Valor Finis
# objects only, and must never accidentally reach an unrelated future
# public object added by something other than this Alembic chain.
APPLICATION_TABLES_SQL = (
    "public.categories, public.expenses, public.budgets, "
    "public.budget_versions, public.goals, public.goal_transactions, "
    "public.accounts, public.account_transactions, public.income, "
    "public.receipts, public.user_financial_settings, "
    "public.alembic_version"
)

# Supabase's Data API (PostgREST) roles. None of these exist on local/CI
# PostgreSQL (confirmed empirically against valor_test and the CI
# service container - both define only the default postgres superuser),
# so every statement naming one of these roles is wrapped in a
# pg_roles existence check and becomes a safe no-op there, while doing
# real work against a real Supabase project.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"


def upgrade() -> None:
    """
    Revokes Supabase Data API (PostgREST) access to Valor Finis
    application tables (VF-SEC-01).

    What:
        1. For each of anon/authenticated/service_role that exists on
           the connected cluster, revokes ALL privileges (SELECT,
           INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER) on
           the 12 explicitly-listed application tables, including
           alembic_version.
        2. For the same roles, removes the postgres role's default
           privileges for FUTURE tables/sequences/functions created in
           the public schema - otherwise a brand-new Alembic-created
           table would silently inherit the same broad Data API access
           the existing tables are being stripped of here.
        3. Revokes the default EXECUTE-on-functions grant PostgreSQL
           extends to PUBLIC by default for future functions in public
           (a plain Postgres default, unrelated to Supabase roles - this
           statement needs no role-existence guard since PUBLIC always
           exists).

    Why:
        Discovery (VF-SEC-01) confirmed the intended and actual
        architecture is mobile -> Supabase Auth -> FastAPI ->
        SQLAlchemy -> PostgreSQL, never mobile/anything -> Supabase
        Data API -> business tables: zero Data API (.from(...)/
        PostgREST) usage exists anywhere in this repository, and the
        FastAPI backend itself connects to PostgreSQL directly via
        psycopg2, never through PostgREST, so it does not depend on
        anon/authenticated/service_role privileges at all. Given that,
        those three roles having broad CRUD privileges on business
        tables (the verified pre-VF-SEC-01 production state) is pure,
        unnecessary exposure: anyone holding the project's anon key
        (inherently public - it ships inside the mobile bundle) could
        otherwise read/write any user's financial data directly,
        bypassing every FastAPI-layer ownership check, FX snapshot
        rule, ledger-projection synchronization, and archived-account
        rule this codebase enforces. This migration closes that gap by
        making FastAPI the only reachable business-data gateway, at the
        database privilege level, while leaving Supabase Auth, Supabase
        Storage, and the Data API mechanism itself untouched (Auth and
        Storage are structurally independent systems - see
        docs/database-schema.md's VF-SEC-01 section).

        RLS is deliberately NOT enabled here: once these roles have no
        table privileges at all, the tables are already unreachable via
        Data API regardless of RLS, so RLS would add policy-authoring
        surface area for no additional protection in this slice. It
        remains available as a future defense-in-depth layer if direct
        Data API access to any of these tables is ever intentionally
        reintroduced.

        Schema USAGE on the public schema is deliberately left
        untouched - only object-level privileges are revoked here.

    This migration changes privileges only: no table, column, or
    constraint is added, dropped, or modified.
    """

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE {APPLICATION_TABLES_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM %I',
                        target_role
                    );
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM %I',
                        target_role
                    );
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'REVOKE EXECUTE ON FUNCTIONS FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )

    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )


def downgrade() -> None:
    """
    Restores legacy Supabase Data API (PostgREST) access to Valor Finis
    application tables (VF-SEC-01) as an emergency rollback.

    What (reverses upgrade() in opposite order):
        1. Restores the default EXECUTE-on-functions grant to PUBLIC.
        2. Restores the postgres role's default privileges for future
           tables/sequences/functions to anon/authenticated/service_role
           (same grant set the platform default extended before
           upgrade: SELECT/INSERT/UPDATE/DELETE on tables, USAGE/
           SELECT/UPDATE on sequences, EXECUTE on functions).
        3. Restores SELECT, INSERT, UPDATE, DELETE on the 12 explicit
           application tables to anon/authenticated/service_role.

        Every statement is guarded the same way upgrade()'s are: a
        pg_roles existence check per role, so downgrading on local/CI
        PostgreSQL (which has none of these roles) is also a safe
        no-op.

    Why this is an intentionally incomplete ACL restoration:
        Downgrading this migration intentionally reopens the legacy
        Data API exposure for these application tables and should only
        be performed as an emergency rollback, never as routine schema
        evolution. It deliberately does NOT restore TRUNCATE,
        REFERENCES, or TRIGGER privileges - those were never required
        for ordinary Data API (PostgREST) CRUD operation, so
        reintroducing them here would recreate a broader legacy surface
        than the rollback actually needs to unblock. This is therefore
        an operational rollback to a working Data API state, not a
        byte-for-byte restoration of the original overly-broad
        production ACLs.
    """

    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "GRANT EXECUTE ON FUNCTIONS TO PUBLIC"
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
                        target_role
                    );
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
                        target_role
                    );
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                        'GRANT EXECUTE ON FUNCTIONS TO %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {APPLICATION_TABLES_SQL} TO %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )
