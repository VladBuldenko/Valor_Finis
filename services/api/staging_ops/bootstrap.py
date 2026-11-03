"""
Staging-only database bootstrap (OPS03 section 2.5a).

What:
    Builds an EMPTY, unmigrated staging database to the single repository head
    through the controlled `alembic upgrade head` interface, then verifies the
    result and records sanitized evidence.

Why:
    The production guarded runner moves one database between exact revisions
    and refuses an empty one; it must not be loosened to bootstrap. This is the
    separate, staging-only procedure with its own identity guard. Every
    mutation sits behind `Operations.run_alembic`, which is reached only after
    every check below passed, and the child process re-verifies the identity on
    its own connection (staging_ops/binding.py).
"""

from typing import Callable, Mapping, Optional

from staging_ops.errors import StagingRefused
from staging_ops.evidence import EvidenceRecord, utc_now, write_evidence
from staging_ops.identity import (
    ConfiguredTarget,
    DatabaseFacts,
    VerifiedTarget,
    assert_same_identity,
    verify_configuration,
    verify_facts,
)
from staging_ops.operations import Operations, child_environment
from staging_ops.redaction import redact
from staging_ops.target_config import ApprovedTargets

# The only Alembic command the bootstrap can issue. Not configurable.
UPGRADE_ARGUMENTS = ("upgrade", "head")


# Runs the configuration, Supabase and connected-identity checks.
# Parameters:
# - record: evidence record filled in as checks pass.
# Returns:
# - (ConfiguredTarget, VerifiedTarget, DatabaseFacts)
# Raises:
# - StagingRefused: before any mutation.
def verify_target(
    environment_flag: Optional[str],
    staging_id: Optional[str],
    environ: Mapping[str, str],
    approved: ApprovedTargets,
    operations: Operations,
    record: EvidenceRecord,
    require_oid: bool = True,
):
    configured = verify_configuration(environment_flag, staging_id, environ, approved, require_oid=require_oid)
    record.describe_target(configured)
    record.step("configuration-allowlist-denylist")

    operations.supabase_probe(configured, environ)
    record.step("supabase-project")

    facts = operations.probe(configured)
    verified = verify_facts(configured, facts)
    record.database_oid = verified.oid
    record.server_major = verified.server_version_num // 10000
    record.step("connected-database-identity")

    return configured, verified, facts


# Builds an empty verified database to head. Shared by bootstrap and reset.
# Parameters:
# - verified: identity captured earlier.
# - environ: validated process environment.
# - operations: injected capabilities.
# - record: evidence record; outcome becomes FAILED just before the mutation.
# - say: sink for operator-facing, already redacted text.
def build_to_head(
    configured: ConfiguredTarget,
    verified: VerifiedTarget,
    environ: Mapping[str, str],
    operations: Operations,
    record: EvidenceRecord,
    say: Callable[[str], None],
) -> None:
    heads = tuple(operations.repository_heads())

    if len(heads) != 1:
        raise StagingRefused("HEADS_NOT_SINGLE", "the repository must have exactly one Alembic head")

    # Re-probe immediately before the mutation: identity AND emptiness are
    # judged on fresh facts, never on the first probe.
    fresh: DatabaseFacts = operations.probe(configured)
    assert_same_identity(verified, fresh)
    record.step("identity-unchanged-before-mutation")

    if fresh.alembic_revisions is not None:
        raise StagingRefused("REVISION_UNEXPECTED", "the database already has an Alembic version table; bootstrap only builds an unmigrated database")

    if fresh.unexpected_objects:
        raise StagingRefused("DATABASE_NOT_EMPTY", "the database already contains schema objects; bootstrap never touches a non-empty database")

    record.step("database-empty-and-unmigrated")

    record.outcome = "FAILED"  # from here a stop is a failure after mutation began
    result = operations.run_alembic(UPGRADE_ARGUMENTS, child_environment(environ, verified, require_empty=True))
    record.details["alembic_exit_code"] = result.returncode

    if result.returncode != 0:
        tail = redact(result.output, [environ.get("DATABASE_URL", ""), environ.get("SUPABASE_PUBLISHABLE_KEY", "")])
        say("alembic output (redacted, last lines):\n" + "\n".join(tail.splitlines()[-15:]))
        raise StagingRefused("UPGRADE_FAILED", f"alembic upgrade head failed with exit code {result.returncode}; the database may be partly built, run the reset procedure")

    record.step("alembic-upgrade-head")

    after = operations.probe(configured)
    assert_same_identity(verified, after)

    if after.alembic_revisions != heads:
        raise StagingRefused("REVISION_MISMATCH", "the database revision does not equal the single repository head")

    expected = set(operations.expected_tables()) | {"alembic_version"}

    if set(after.public_tables) != expected:
        raise StagingRefused("SCHEMA_UNEXPECTED_OBJECTS", "the tables in public differ from the models after the upgrade")

    record.details.update({"alembic_head": heads[0], "alembic_current": after.alembic_revisions[0], "table_count": len(after.public_tables)})
    record.step("alembic-current-equals-head")
    record.step("schema-tables-match-models")
    record.outcome = "OK"


# Staging-only bootstrap entry point.
# Parameters:
# - environment_flag: the explicit --environment value.
# - staging_id: approved entry (--staging).
# - environ: process environment copy.
# - approved: owner-approved targets.
# - operations: capabilities (real or injected).
# - evidence_dir: where to write the sanitized record (None: do not write).
# - say: sink for operator-facing text.
# Returns:
# - The EvidenceRecord (outcome OK).
# Raises:
# - StagingRefused: nothing was changed when outcome is REFUSED; FAILED means
#   the upgrade started and the database must be reset before reuse.
def bootstrap(
    environment_flag: Optional[str],
    staging_id: Optional[str],
    environ: Mapping[str, str],
    approved: ApprovedTargets,
    operations: Operations,
    evidence_dir: Optional[str] = None,
    say: Callable[[str], None] = print,
    clock=None,
) -> EvidenceRecord:
    record = EvidenceRecord(operation="bootstrap", started_at=utc_now(clock))

    try:
        configured, verified, _facts = verify_target(environment_flag, staging_id, environ, approved, operations, record)
        build_to_head(configured, verified, environ, operations, record, say)
    except StagingRefused as error:
        record.code = error.code
        error.mutated = record.outcome == "FAILED"
        raise
    finally:
        record.finished_at = utc_now(clock)

        if evidence_dir:
            write_evidence(evidence_dir, record)

    return record
