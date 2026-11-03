"""
Fail-closed staging identity guard.

What:
    Decides, before any mutation, whether a requested database is the
    owner-approved staging database. Two stages:
    1. `verify_configuration` (offline): explicit environment flag, exact
       host/port/database allowlist match, production denylist, `_staging`
       suffix, Supabase project, no contradictory or override-capable
       configuration.
    2. `verify_facts` / `assert_same_identity` (online facts): the database
       that actually answered must be the approved one (name, pinned oid, a
       primary server) and must stay the same until the mutation.

Why:
    A name suffix or an environment variable name proves nothing. The guard
    never trusts the URL alone: it checks the facts reported by the server
    and binds the mutation connection to them (see database.py and the
    Alembic hook in staging_ops/binding.py). QA-0's fingerprint helper is
    evidence for a mobile build and does not replace this guard.
"""

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from staging_ops.errors import StagingRefused
from staging_ops.target_config import (
    STAGING_DATABASE_SUFFIX,
    ApprovedTargets,
    StagingEntry,
    normalize_host,
)

ENVIRONMENT_NAME = "staging"

# libpq variables that can silently redirect or weaken a connection that the
# URL appears to describe. The single source of truth is DATABASE_URL.
FORBIDDEN_LIBPQ_VARIABLES = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGOPTIONS",
    "PGSSLMODE",
    "PGTARGETSESSIONATTRS",
    "PGSYSCONFDIR",
)

ALLOWED_URL_PARAMETERS = {"sslmode", "connect_timeout", "application_name"}
STRONG_SSL_MODES = {"require", "verify-ca", "verify-full"}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

_DB_HOST_REF = re.compile(r"^(?:db\.)?([a-z0-9]{10,40})\.supabase\.co$")
_POOLER_USER_REF = re.compile(r"^[a-z_]+\.([a-z0-9]{10,40})$")
_SUPABASE_API_HOST = re.compile(r"^([a-z0-9]{10,40})\.supabase\.co$")


@dataclass(frozen=True)
class ConfiguredTarget:
    """The approved target a request resolved to. The URL never appears in repr."""

    staging_id: str
    host: str
    port: int
    database: str
    oid: Optional[int]
    supabase_project_ref: str
    database_url: str = field(repr=False)

    # Text the operator must type back to confirm a reset.
    def confirmation_phrase(self) -> str:
        return f"{self.staging_id}/{self.database}@{self.host}:{self.port}"


@dataclass(frozen=True)
class DatabaseFacts:
    """What the connected server reports about itself (no secrets)."""

    database: str
    oid: int
    postmaster_start: str
    in_recovery: bool
    server_version_num: int
    # Relations, types and functions in `public` that no extension owns.
    unexpected_objects: int
    # None means the alembic_version table does not exist.
    alembic_revisions: Optional[Tuple[str, ...]]
    # Ordinary tables in `public` (used by the post-bootstrap check).
    public_tables: Tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedTarget:
    """A configured target plus the server facts it was verified against."""

    configured: ConfiguredTarget
    oid: int
    postmaster_start: str
    server_version_num: int

    def binding(self) -> dict:
        return {"database": self.configured.database, "oid": self.oid, "postmaster_start": self.postmaster_start}


def _parse_database_url(raw: str):
    try:
        url = make_url(raw)
    except Exception:
        raise StagingRefused("CONFIG_MALFORMED", "DATABASE_URL could not be parsed") from None

    if url.drivername not in ("postgresql", "postgresql+psycopg2"):
        raise StagingRefused("CONFIG_MALFORMED", "DATABASE_URL must be a PostgreSQL URL")

    host = url.host

    if not host or "," in host or host.startswith("/"):
        raise StagingRefused("CONFIG_MALFORMED", "DATABASE_URL must name exactly one TCP host")

    if not url.username or not url.database:
        raise StagingRefused("CONFIG_MALFORMED", "DATABASE_URL must name a user and a database")

    unknown = set(url.query) - ALLOWED_URL_PARAMETERS

    if unknown:
        raise StagingRefused("CONFIG_MALFORMED", "DATABASE_URL carries parameters that can override the identity")

    return url


def _project_refs(host: str, username: str) -> set:
    refs = set()

    match = _DB_HOST_REF.match(host)
    if match:
        refs.add(match.group(1))

    match = _POOLER_USER_REF.match(username)
    if match:
        refs.add(match.group(1))

    return refs


def _host_is_denied(host: str, denied_hosts) -> bool:
    return any(host == denied or host.endswith("." + denied) for denied in denied_hosts)


def _supabase_project_ref(raw: str) -> str:
    parts = urlsplit(raw)
    match = _SUPABASE_API_HOST.match((parts.hostname or "").lower())

    if (
        parts.scheme != "https"
        or not match
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise StagingRefused("SUPABASE_URL_INVALID", "SUPABASE_URL must be https://<project-ref>.supabase.co")

    return match.group(1)


# Verifies the requested configuration against the owner-approved targets.
# Nothing here touches the network or a database.
# Parameters:
# - environment_flag: value of the explicit --environment argument (None if absent).
# - staging_id: approved staging entry the operator names (--staging).
# - environ: the effective process environment (copied by the caller).
# - approved: owner-approved targets and production denylist.
# - require_oid: True for every mutating operation; the read-only
#   `identify` command passes False so the owner can learn the oid.
# Returns:
# - ConfiguredTarget bound to exactly one approved entry.
# Raises:
# - StagingRefused: on the first missing, malformed, contradictory,
#   denylisted or non-allowlisted element.
def verify_configuration(
    environment_flag: Optional[str],
    staging_id: Optional[str],
    environ: Mapping[str, str],
    approved: ApprovedTargets,
    require_oid: bool = True,
) -> ConfiguredTarget:
    if environment_flag is None:
        raise StagingRefused("ENV_FLAG_MISSING", "--environment staging is required")

    if environment_flag != ENVIRONMENT_NAME:
        raise StagingRefused("ENV_FLAG_WRONG", "--environment must be exactly 'staging'")

    entry: Optional[StagingEntry] = next((item for item in approved.staging if item.staging_id == staging_id), None)

    if entry is None:
        raise StagingRefused("STAGING_ID_UNKNOWN", "the named staging entry is not in the approved targets")

    for variable in FORBIDDEN_LIBPQ_VARIABLES:
        if environ.get(variable):
            raise StagingRefused("CONFIG_OVERRIDE", f"{variable} must be unset: it can override the validated connection")

    for variable in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"):
        if not (environ.get(variable) or "").strip():
            raise StagingRefused("CONFIG_MISSING", f"{variable} must be set")

    if (environ.get("AUTH_MODE") or "").strip().lower() != "supabase":
        raise StagingRefused("AUTH_MODE_CONTRADICTORY", "staging requires AUTH_MODE=supabase")

    denylist = approved.denylist

    if not denylist.database_hosts or not denylist.supabase_project_refs:
        raise StagingRefused("DENYLIST_EMPTY", "the production denylist must list at least one database host and one Supabase project")

    url = _parse_database_url(environ["DATABASE_URL"])
    host = normalize_host(url.host)
    port = url.port or 5432
    database = url.database
    refs = _project_refs(host, url.username)
    supabase_ref = _supabase_project_ref(environ["SUPABASE_URL"].strip())

    if (
        _host_is_denied(host, denylist.database_hosts)
        or database in denylist.database_names
        or (refs | {supabase_ref}) & set(denylist.supabase_project_refs)
    ):
        raise StagingRefused("DENYLIST_HIT", "the target matches an identifier on the production denylist")

    if port == 6543 or "pgbouncer" in host:
        raise StagingRefused("POOLER_UNSUPPORTED", "a transaction-mode pooler cannot hold the advisory lock; use a direct or session-mode endpoint")

    sslmode = url.query.get("sslmode")

    if host not in LOOPBACK_HOSTS and sslmode not in STRONG_SSL_MODES:
        raise StagingRefused("TLS_REQUIRED", "a remote database requires sslmode=require, verify-ca or verify-full")

    if host != entry.host or port != entry.port:
        raise StagingRefused("TARGET_NOT_ALLOWLISTED", "the database host and port do not equal the approved staging entry")

    if database != entry.database:
        raise StagingRefused("DATABASE_NOT_ALLOWLISTED", "the database name does not equal the approved staging entry")

    if not database.endswith(STAGING_DATABASE_SUFFIX) or database == STAGING_DATABASE_SUFFIX:
        raise StagingRefused("DATABASE_SUFFIX", "the database name must end with _staging")

    if supabase_ref != entry.supabase_project_ref:
        raise StagingRefused("SUPABASE_PROJECT_MISMATCH", "SUPABASE_URL is not the approved staging Supabase project")

    if refs and refs != {entry.supabase_project_ref}:
        raise StagingRefused("SUPABASE_PROJECT_MISMATCH", "the database belongs to a different Supabase project than SUPABASE_URL")

    if require_oid and entry.oid is None:
        raise StagingRefused("OID_NOT_PINNED", "the approved entry has no database oid; run identify and have the owner record it")

    return ConfiguredTarget(
        staging_id=entry.staging_id,
        host=host,
        port=port,
        database=database,
        oid=entry.oid,
        supabase_project_ref=entry.supabase_project_ref,
        database_url=environ["DATABASE_URL"],
    )


# Verifies the facts reported by the connected server.
# Parameters:
# - configured: the target that passed verify_configuration.
# - facts: what the server reports about itself.
# Returns:
# - VerifiedTarget carrying the identity the mutation connection is bound to.
# Raises:
# - StagingRefused: the answering database is not the approved one.
def verify_facts(configured: ConfiguredTarget, facts: DatabaseFacts) -> VerifiedTarget:
    if facts.database != configured.database:
        raise StagingRefused("CONNECTED_DATABASE_MISMATCH", "the connected database is not the validated target")

    if not facts.database.endswith(STAGING_DATABASE_SUFFIX):
        raise StagingRefused("DATABASE_SUFFIX", "the connected database name must end with _staging")

    if configured.oid is not None and facts.oid != configured.oid:
        raise StagingRefused("CONNECTED_OID_MISMATCH", "the connected database oid is not the approved oid")

    if facts.in_recovery:
        raise StagingRefused("NOT_PRIMARY", "the connected server is a read-only standby")

    return VerifiedTarget(
        configured=configured,
        oid=facts.oid,
        postmaster_start=facts.postmaster_start,
        server_version_num=facts.server_version_num,
    )


# Re-checks the identity immediately before a mutation.
# This closes the gap between the first check and the mutation: a changed
# database, oid or server start is a refusal.
# Parameters:
# - verified: identity captured earlier.
# - facts: freshly probed facts.
# Raises:
# - StagingRefused: IDENTITY_CHANGED when anything differs.
def assert_same_identity(verified: VerifiedTarget, facts: DatabaseFacts) -> None:
    if (
        facts.database != verified.configured.database
        or facts.oid != verified.oid
        or facts.postmaster_start != verified.postmaster_start
        or facts.in_recovery
    ):
        raise StagingRefused("IDENTITY_CHANGED", "the database identity changed after it was verified")
