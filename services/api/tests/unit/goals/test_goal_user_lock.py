import ast
import hashlib
import inspect
from uuid import UUID

from app.modules.goals import goal_user_lock
from app.modules.goals.goal_user_lock import (
    ADVISORY_LOCK_SQL,
    GOAL_USER_LOCK_NAMESPACE,
    compute_goal_user_lock_key,
)

# VF-020D3 unit tests (no database) for the L0 key contract
# (docs/modules/smart-goals-rules.md section 14.5, P69): namespace bytes,
# SHA-256 over namespace + raw UUID bytes, first 8 bytes, big-endian, signed.

KNOWN_USER = UUID("12345678-1234-5678-1234-567812345678")
# Independently computed fixture: first 8 SHA-256 bytes of
# b"valor-finis:l0:user:v1:" + KNOWN_USER.bytes, read as a signed big-endian
# int64. A change of namespace, hash, byte count, endianness or UUID encoding
# changes this number.
KNOWN_USER_KEY = -224992839317855138


def test_namespace_bytes_are_exact() -> None:
    assert GOAL_USER_LOCK_NAMESPACE == b"valor-finis:l0:user:v1:"


def test_known_uuid_produces_the_exact_fixture_key() -> None:
    assert compute_goal_user_lock_key(KNOWN_USER) == KNOWN_USER_KEY


def test_key_is_the_documented_derivation() -> None:
    digest = hashlib.sha256(b"valor-finis:l0:user:v1:" + KNOWN_USER.bytes).digest()

    assert compute_goal_user_lock_key(KNOWN_USER) == int.from_bytes(
        digest[:8], byteorder="big", signed=True
    )


def test_key_uses_raw_uuid_bytes_not_the_string_form() -> None:
    string_digest = hashlib.sha256(
        b"valor-finis:l0:user:v1:" + str(KNOWN_USER).encode()
    ).digest()
    string_key = int.from_bytes(string_digest[:8], byteorder="big", signed=True)

    assert compute_goal_user_lock_key(KNOWN_USER) != string_key


def test_same_uuid_gives_same_key_and_different_uuids_normally_differ() -> None:
    other = UUID("87654321-4321-8765-4321-876543218765")

    assert compute_goal_user_lock_key(KNOWN_USER) == compute_goal_user_lock_key(
        UUID(str(KNOWN_USER))
    )
    assert compute_goal_user_lock_key(KNOWN_USER) != compute_goal_user_lock_key(other)


def test_key_is_within_the_signed_bigint_range() -> None:
    for value in range(200):
        key = compute_goal_user_lock_key(UUID(int=value * 7919 + 1))

        assert -(2**63) <= key < 2**63


def test_implementation_is_deterministic_and_transaction_scoped() -> None:
    tree = ast.parse(inspect.getsource(goal_user_lock))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "hash" not in called_names  # never the per-process Python hash()
    assert "random" not in imported and "secrets" not in imported
    assert ADVISORY_LOCK_SQL == "SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"
    assert "pg_advisory_lock(" not in ADVISORY_LOCK_SQL  # never session-level
