import hashlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# VF-020D3: L0, the user-wide Goal write lock (contract:
# docs/modules/smart-goals-rules.md section 14.5, P68, P69).
#
# L0 is a transaction-scoped PostgreSQL advisory lock keyed by the user. Every
# Goal write (create, edit, status change, delete, tracked and linked
# contributions/withdrawals, priority reorder) acquires it FIRST, before any
# Goal or Account row lock, in the SAME session/transaction that performs the
# write, and holds it until that transaction's commit or rollback. Read-only
# Goal requests, occupied-key idempotent replays and Account delete / currency
# change never take it.
#
# A key collision between two users only serializes them; it can never mix
# ownership or data, because every row is still scoped by user_id.

# The exact namespace of the contract. Changing it changes every user's key,
# so it is versioned in the bytes themselves.
GOAL_USER_LOCK_NAMESPACE = b"valor-finis:l0:user:v1:"

# Tells the reader of a pg_locks row which advisory lock family this is; used
# only by tests and diagnostics.
ADVISORY_LOCK_SQL = "SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"


# Derives the L0 advisory-lock key of a user.
# SHA-256 over the namespace bytes plus the user's raw 16 UUID bytes (not the
# string form); the first 8 digest bytes are read big-endian as a signed
# 64-bit integer, which is exactly PostgreSQL's bigint range. Deterministic
# and process-independent: no Python hash(), no salt.
# Parameters:
# - user_id: the authenticated user's UUID.
# Returns:
# - Signed int64 usable as the argument of pg_advisory_xact_lock(bigint).
def compute_goal_user_lock_key(user_id: UUID) -> int:
    digest = hashlib.sha256(GOAL_USER_LOCK_NAMESPACE + user_id.bytes).digest()

    return int.from_bytes(digest[:8], byteorder="big", signed=True)


# Acquires L0 for a user inside the session's current transaction, waiting
# until it is available. The lock is released only by that transaction's
# commit or rollback, so callers must not commit between acquiring it and
# finishing the protected write.
# Parameters:
# - db_session: the session (and transaction) that performs the Goal write.
# - user_id: the authenticated user's UUID.
# Returns:
# - None.
def acquire_goal_user_lock(db_session: Session, user_id: UUID) -> None:
    db_session.execute(
        text(ADVISORY_LOCK_SQL),
        {"lock_key": compute_goal_user_lock_key(user_id)},
    )
