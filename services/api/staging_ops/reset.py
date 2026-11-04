"""
Staging reset: DISABLED / DEFERRED (owner-approved scope change, VF-QA-1 MVP simplification).

What:
    The automatic reset is not available. `reset()` always refuses, before it
    reads any configuration, opens any connection or runs any SQL. The
    destructive implementation (and its scope-confinement machinery) was
    removed from the code base; it remains only in Git history (commit
    51c05a1) and its findings stay documented in the staging runbook.

Why:
    An independent review reproduced a concurrent-DDL case in which a reset
    reported success while another session's uncommitted DDL referencing an
    application type left an out-of-scope table unreadable. Rather than build
    a more complex reset now, the capability is withdrawn. If a staging
    database becomes unusable, the recovery path is to STOP and request a newly
    provisioned, separately approved, empty staging database; nothing here
    drops or recreates an existing database.

Do not add a replacement destructive command here. Re-enabling a reset is a
later owner decision with its own task and review.
"""

from staging_ops.errors import StagingRefused

RESET_DISABLED_MESSAGE = (
    "the staging reset is disabled (deferred by the owner); nothing was read, connected to or changed. "
    "If the staging database is unusable, stop and request a newly provisioned, separately approved, empty staging database"
)


# Always refuses. Accepts any arguments so no caller can reach a different behavior by signature.
# Raises:
# - StagingRefused: RESET_DISABLED, never marked as mutated.
def reset(*_arguments, **_keywords):
    raise StagingRefused("RESET_DISABLED", RESET_DISABLED_MESSAGE)
