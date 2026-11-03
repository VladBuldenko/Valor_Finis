"""
Owner-approved staging targets and production denylist.

What:
    Loads and strictly validates the operator-held approved-targets file.

Why:
    The identity guard compares the requested database with identifiers the
    owner approved. Those identifiers (hosts, project references, database
    names, one database oid) are not secrets, but they are never committed:
    the file must live outside the repository working tree. Specification:
    docs/operations/staging/approved-targets-spec.md.
"""

import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from staging_ops.errors import StagingRefused



# The git working tree this package lives in, or None when it runs outside one
# (for example in the API container image, where there is nothing to commit).
def _repository_root() -> Optional[Path]:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent

    return None


REPOSITORY_ROOT = _repository_root()

SCHEMA_VERSION = 1
STAGING_DATABASE_SUFFIX = "_staging"

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.\-]*[a-z0-9])?$")
_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PROJECT_REF = re.compile(r"^[a-z0-9]{10,40}$")
_STAGING_ID = re.compile(r"^STG-[0-9]+$")

_TOP_KEYS = {"schema_version", "staging", "production_denylist"}
_STAGING_KEYS = {"id", "database", "supabase_project_ref", "approved_by", "approved_on"}
_DATABASE_KEYS = {"host", "port", "name", "oid"}
_DENYLIST_KEYS = {"database_hosts", "supabase_project_refs", "database_names", "recorded_by", "recorded_on"}


@dataclass(frozen=True)
class StagingEntry:
    """One owner-approved staging environment."""

    staging_id: str
    host: str
    port: int
    database: str
    oid: Optional[int]
    supabase_project_ref: str


@dataclass(frozen=True)
class ProductionDenylist:
    """Owner-recorded production identifiers (never secrets)."""

    database_hosts: Tuple[str, ...]
    supabase_project_refs: Tuple[str, ...]
    database_names: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ApprovedTargets:
    staging: Tuple[StagingEntry, ...]
    denylist: ProductionDenylist


# Normalizes a host name or IP literal for comparison.
# Parameters:
# - value: host as written by the owner or found in a URL.
# Returns:
# - Lower-case host without a trailing dot.
# Raises:
# - StagingRefused: the value is not a plain host name or IP address.
def normalize_host(value: Any) -> str:
    if not isinstance(value, str):
        raise StagingRefused("CONFIG_MALFORMED", "a host must be a string")

    host = value.strip().lower().rstrip(".")

    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    if not _HOST.match(host) or ".." in host:
        raise StagingRefused("CONFIG_MALFORMED", "a host is not a plain host name or IP address")

    return host


def _require_keys(mapping: Any, allowed: set, required: set, what: str) -> Mapping[str, Any]:
    if not isinstance(mapping, dict):
        raise StagingRefused("CONFIG_MALFORMED", f"{what} must be an object")

    unknown = set(mapping) - allowed
    missing = required - set(mapping)

    if unknown or missing:
        raise StagingRefused("CONFIG_MALFORMED", f"{what} has missing or unknown fields")

    return mapping


def _iso_date(value: Any, what: str) -> None:
    try:
        if not isinstance(value, str):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise StagingRefused("CONFIG_MALFORMED", f"{what} must be an ISO date") from None


def _non_blank(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StagingRefused("CONFIG_MALFORMED", f"{what} must be a non-blank string")

    return value.strip()


def _string_list(value: Any, what: str, normalize) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise StagingRefused("CONFIG_MALFORMED", f"{what} must be a list")

    return tuple(normalize(item) for item in value)


def _project_ref(value: Any) -> str:
    if not isinstance(value, str) or not _PROJECT_REF.match(value):
        raise StagingRefused("CONFIG_MALFORMED", "a Supabase project reference is malformed")

    return value


def _database_name(value: Any) -> str:
    if not isinstance(value, str) or not _DATABASE_NAME.match(value):
        raise StagingRefused("CONFIG_MALFORMED", "a database name is malformed")

    return value


# Validates the parsed approved-targets document.
# This function exists separately from file loading so the rules are unit
# tested without touching the file system.
# Parameters:
# - document: parsed JSON.
# Returns:
# - ApprovedTargets.
# Raises:
# - StagingRefused: any missing, unknown, malformed or contradictory field.
def parse_approved_targets(document: Any) -> ApprovedTargets:
    top = _require_keys(document, _TOP_KEYS, _TOP_KEYS, "approved targets")

    if top["schema_version"] != SCHEMA_VERSION or isinstance(top["schema_version"], bool):
        raise StagingRefused("CONFIG_MALFORMED", "unsupported approved-targets schema version")

    raw_denylist = _require_keys(top["production_denylist"], _DENYLIST_KEYS, _DENYLIST_KEYS, "production denylist")
    _non_blank(raw_denylist["recorded_by"], "denylist recorded_by")
    _iso_date(raw_denylist["recorded_on"], "denylist recorded_on")

    denylist = ProductionDenylist(
        database_hosts=_string_list(raw_denylist["database_hosts"], "denylist database_hosts", normalize_host),
        supabase_project_refs=_string_list(raw_denylist["supabase_project_refs"], "denylist supabase_project_refs", _project_ref),
        database_names=_string_list(raw_denylist["database_names"], "denylist database_names", _database_name),
    )

    if not isinstance(top["staging"], list):
        raise StagingRefused("CONFIG_MALFORMED", "staging must be a list")

    entries = []

    for raw in top["staging"]:
        item = _require_keys(raw, _STAGING_KEYS, _STAGING_KEYS, "a staging entry")
        database = _require_keys(item["database"], _DATABASE_KEYS, _DATABASE_KEYS - {"oid"}, "a staging database")
        staging_id = item["id"]

        if not isinstance(staging_id, str) or not _STAGING_ID.match(staging_id):
            raise StagingRefused("CONFIG_MALFORMED", "a staging id must look like STG-<number>")

        _non_blank(item["approved_by"], "approved_by")
        _iso_date(item["approved_on"], "approved_on")

        port = database["port"]
        oid = database.get("oid")

        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise StagingRefused("CONFIG_MALFORMED", "a staging port is malformed")

        if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int) or oid <= 0):
            raise StagingRefused("CONFIG_MALFORMED", "a staging database oid is malformed")

        name = _database_name(database["name"])

        if not name.endswith(STAGING_DATABASE_SUFFIX) or name == STAGING_DATABASE_SUFFIX:
            raise StagingRefused("CONFIG_MALFORMED", "a staging database name must end with _staging")

        entries.append(
            StagingEntry(
                staging_id=staging_id,
                host=normalize_host(database["host"]),
                port=port,
                database=name,
                oid=oid,
                supabase_project_ref=_project_ref(item["supabase_project_ref"]),
            )
        )

    if len({entry.staging_id for entry in entries}) != len(entries):
        raise StagingRefused("CONFIG_CONTRADICTORY", "duplicate staging id")

    if len({(entry.host, entry.port, entry.database) for entry in entries}) != len(entries):
        raise StagingRefused("CONFIG_CONTRADICTORY", "duplicate staging database")

    for entry in entries:
        if (
            any(entry.host == denied or entry.host.endswith("." + denied) for denied in denylist.database_hosts)
            or entry.supabase_project_ref in denylist.supabase_project_refs
            or entry.database in denylist.database_names
        ):
            raise StagingRefused("CONFIG_CONTRADICTORY", "a staging entry overlaps the production denylist")

    return ApprovedTargets(staging=tuple(entries), denylist=denylist)


# Loads the operator-held approved-targets file.
# The file must live outside the repository working tree (so identifiers
# are never committed by accident) and must not be writable by group or
# others.
# Parameters:
# - path: file path given on the command line.
# Returns:
# - ApprovedTargets.
# Raises:
# - StagingRefused: file missing, unsafe location or permissions, or invalid.
def load_approved_targets(path: str) -> ApprovedTargets:
    try:
        resolved = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise StagingRefused("CONFIG_MISSING", "the approved-targets file does not exist") from None

    if REPOSITORY_ROOT is not None and (resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents):
        raise StagingRefused("CONFIG_LOCATION", "the approved-targets file must be stored outside the repository")

    info = os.stat(resolved)

    if not stat.S_ISREG(info.st_mode):
        raise StagingRefused("CONFIG_MALFORMED", "the approved-targets path is not a regular file")

    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise StagingRefused("CONFIG_PERMISSIONS", "the approved-targets file must not be writable by group or others")

    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StagingRefused("CONFIG_MALFORMED", "the approved-targets file is not valid JSON") from None

    return parse_approved_targets(document)
