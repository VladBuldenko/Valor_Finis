import hashlib
import json
from typing import Dict, Optional, Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# VF-MVP-CORE-002: building blocks shared by the Income and Expense create
# idempotency (client_request_id). Kept free of any domain import so both
# modules use exactly the same fingerprint and lock rules.

# Bumping this changes every stored fingerprint, so it is part of the hashed
# bytes: a future format can never be mistaken for a v1 one.
FINGERPRINT_VERSION = "v1"

# Namespace of the per-key advisory lock (see acquire_create_key_lock).
CREATE_KEY_LOCK_NAMESPACE = b"valor-finis:create-key:v1:"

ADVISORY_LOCK_SQL = "SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"

FingerprintValue = Optional[Union[str, bool, int]]


# Builds the fingerprint of a create request: the SHA-256 (lower-case hex, 64
# characters) of a canonical JSON document holding the version, the operation
# name and the request fields.
# This function exists to remember WHAT a client_request_id was first used for,
# so a replay can be told apart from the same key reused for a different
# request. Income and Expense are editable after creation, so comparing a
# retry with the CURRENT row would turn "created, then edited, then the lost
# response is retried" into a false conflict; the fingerprint is taken once,
# from the request as the server understood it.
# Parameters:
# - operation: a fixed name such as "income.create", so the same fields in two
#   domains never produce the same fingerprint.
# - fields: the request fields, already normalized to canonical strings by the
#   caller (money as a fixed two-decimal string, dates as ISO strings, UUIDs
#   as lower-case strings). Only str, bool, int and None are accepted, so a
#   float or an un-normalized Decimal can never leak into a fingerprint.
# Returns:
# - 64-character lower-case hexadecimal digest.
# Raises:
# - TypeError: a field value has a type that has no canonical form here.
def compute_request_fingerprint(operation: str, fields: Dict[str, FingerprintValue]) -> str:
    for name, value in fields.items():
        if value is not None and not isinstance(value, (str, bool, int)):
            raise TypeError(f"Field {name} has no canonical fingerprint form.")

    document = json.dumps(
        {"version": FINGERPRINT_VERSION, "operation": operation, "fields": fields},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return hashlib.sha256(document.encode("ascii")).hexdigest()


# Derives the advisory-lock key of one (operation, user, client_request_id).
# SHA-256 over the namespace, the operation name and the raw UUID bytes of the
# user and the key; the first 8 digest bytes read as a signed 64-bit integer
# (PostgreSQL's bigint). Deterministic and process-independent (no Python
# hash()). A collision between two different keys only makes them wait for
# each other; it can never mix ownership or data.
def compute_create_key_lock_key(operation: str, user_id: UUID, client_request_id: UUID) -> int:
    digest = hashlib.sha256(
        CREATE_KEY_LOCK_NAMESPACE
        + operation.encode("ascii")
        + b":"
        + user_id.bytes
        + client_request_id.bytes
    ).digest()

    return int.from_bytes(digest[:8], byteorder="big", signed=True)


# Serializes every create that carries the same (operation, user,
# client_request_id) for the rest of the session's current transaction.
# This function exists so that two concurrent requests with one key run one
# after the other: the second then finds the first one's committed record in
# its lookup and replays it, instead of racing it through FX resolution, the
# Account lock and the insert. The unique constraint stays the final
# backstop. The lock is transaction-scoped, so the commit or rollback that ends
# the create releases it; it is never a row or Account lock and never blocks a
# request that has no key.
def acquire_create_key_lock(
    db_session: Session,
    operation: str,
    user_id: UUID,
    client_request_id: UUID,
) -> None:
    db_session.execute(
        text(ADVISORY_LOCK_SQL),
        {"lock_key": compute_create_key_lock_key(operation, user_id, client_request_id)},
    )
