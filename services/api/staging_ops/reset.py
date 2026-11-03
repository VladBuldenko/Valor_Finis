"""
Explicit, destructive staging reset.

What:
    Destroys the application schema and data of ONE verified staging database,
    then rebuilds it to head with the same controlled bootstrap, and records
    sanitized evidence.

Why:
    Reset is never a side effect: nothing calls it after a failed test. It
    requires the full identity guard, a description of the data that will be
    lost, and the operator typing the exact target identity back at an
    interactive terminal. There is no automatic confirmation and no flag that
    skips it. Supabase Auth users and Storage objects are NOT touched.
"""

from typing import Callable, Mapping, Optional

from staging_ops.bootstrap import build_to_head, verify_target
from staging_ops.errors import StagingRefused, unexpected
from staging_ops.evidence import EvidenceRecord, utc_now, write_evidence
from staging_ops.identity import assert_same_identity
from staging_ops.operations import Operations
from staging_ops.target_config import ApprovedTargets


# Reads one line from an interactive terminal.
# Piped or redirected input is refused, so a script cannot confirm on the
# operator's behalf (for example `yes | ...`).
def interactive_confirm(prompt: str) -> str:
    import sys

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise StagingRefused("CONFIRMATION_NOT_INTERACTIVE", "reset must be confirmed at an interactive terminal")

    return input(prompt)


# Staging reset entry point.
# Parameters:
# - confirm: callable returning what the operator typed; None means no
#   confirmation is available and the reset is refused.
# - other parameters: as for bootstrap().
# Returns:
# - The EvidenceRecord (outcome OK).
# Raises:
# - StagingRefused: REFUSED with nothing destroyed, or FAILED after the
#   destroy step started (the database may be empty; run bootstrap).
def reset(
    environment_flag: Optional[str],
    staging_id: Optional[str],
    environ: Mapping[str, str],
    approved: ApprovedTargets,
    operations: Operations,
    confirm: Optional[Callable[[str], str]],
    evidence_dir: Optional[str] = None,
    say: Callable[[str], None] = print,
    clock=None,
) -> EvidenceRecord:
    record = EvidenceRecord(operation="reset", started_at=utc_now(clock))

    try:
        configured, verified, _facts = verify_target(environment_flag, staging_id, environ, approved, operations, record)

        if confirm is None:
            raise StagingRefused("CONFIRMATION_MISSING", "a reset needs an operator confirmation")

        tables, other_objects = operations.describe(verified)
        phrase = configured.confirmation_phrase()
        say(
            "RESET WILL PERMANENTLY DESTROY the application schema and data of this staging database:\n"
            + "".join(f"  {name}: {count} rows\n" for name, count in tables)
            + f"  plus {other_objects} other schema objects (views, sequences, types, functions).\n"
            "Not affected: Supabase Auth users, Storage objects, other schemas.\n"
            "The database is then rebuilt to the Alembic head and must be re-seeded."
        )
        record.details["tables_to_destroy"] = len(tables)
        record.details["rows_to_destroy"] = sum(count for _name, count in tables)

        typed = confirm(f"Type the exact target identity to confirm ({phrase}): ")

        if typed.strip("\r\n") != phrase:
            raise StagingRefused("CONFIRMATION_MISMATCH", "the typed identity does not equal the verified target; nothing was destroyed")

        record.step("operator-confirmed-exact-identity")

        # Identity is re-proved after the (possibly slow) human step.
        assert_same_identity(verified, operations.probe(configured))
        record.step("identity-unchanged-before-destroy")

        record.outcome = "FAILED"  # destroy has begun
        statements = operations.destroy(verified)
        record.details["drop_statements"] = statements
        record.step("application-objects-destroyed")

        emptied = operations.probe(configured)
        assert_same_identity(verified, emptied)

        if emptied.unexpected_objects or emptied.alembic_revisions is not None:
            raise StagingRefused("POST_RESET_CHECK_FAILED", "the database is not empty after the reset")

        record.step("post-reset-database-empty")

        build_to_head(configured, verified, environ, operations, record, say)
    except StagingRefused as error:
        record.code = error.code
        error.mutated = record.outcome == "FAILED"
        raise
    except Exception as error:
        failure = unexpected(error)
        record.code = failure.code
        record.details["error_type"] = type(error).__name__
        failure.mutated = record.outcome == "FAILED"
        raise failure from None
    finally:
        record.finished_at = utc_now(clock)

        if evidence_dir:
            write_evidence(evidence_dir, record)

    return record
