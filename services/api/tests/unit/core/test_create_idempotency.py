"""Pure rules of the Income/Expense create idempotency helper (VF-MVP-CORE-002)."""
import re
from decimal import Decimal
from uuid import UUID

import pytest

from app.core import create_idempotency as helper

FIELDS = {
    "amount": "100.00",
    "currency": "EUR",
    "received_at": "2026-03-04",
    "source": "salary",
    "description": None,
    "account_id": None,
}
USER = UUID("00000000-0000-0000-0000-000000000001")
KEY = UUID("00000000-0000-0000-0000-000000000002")


def test_fingerprint_has_a_fixed_known_vector() -> None:
    # Pinned: changing this value silently invalidates every stored fingerprint (a replay of an
    # old record would become a 409). A deliberate format change must bump FINGERPRINT_VERSION.
    assert helper.compute_request_fingerprint("income.create", FIELDS) == (
        "ede7f63f99a0e1eb069ffcf59c8df45f7f16f07dc4f10eb928315e44c726443f"
    )


def test_fingerprint_is_lowercase_hex_sha256_and_deterministic() -> None:
    first = helper.compute_request_fingerprint("income.create", FIELDS)

    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert helper.compute_request_fingerprint("income.create", dict(FIELDS)) == first


def test_fingerprint_ignores_field_order() -> None:
    reordered = dict(reversed(list(FIELDS.items())))

    assert helper.compute_request_fingerprint("income.create", reordered) == helper.compute_request_fingerprint(
        "income.create", FIELDS
    )


def test_fingerprint_changes_with_every_field_the_operation_and_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    base = helper.compute_request_fingerprint("income.create", FIELDS)
    seen = {base}

    for name, other in (
        ("amount", "100.01"), ("currency", "USD"), ("received_at", "2026-03-05"), ("source", "gift"),
        ("description", ""), ("account_id", "x"),
    ):
        seen.add(helper.compute_request_fingerprint("income.create", {**FIELDS, name: other}))
    seen.add(helper.compute_request_fingerprint("expense.create", FIELDS))
    monkeypatch.setattr(helper, "FINGERPRINT_VERSION", "v2")
    seen.add(helper.compute_request_fingerprint("income.create", FIELDS))

    assert len(seen) == 9


def test_none_and_empty_string_are_different_values() -> None:
    assert helper.compute_request_fingerprint("op", {"description": None}) != helper.compute_request_fingerprint(
        "op", {"description": ""}
    )


def test_values_cannot_be_confused_by_their_content() -> None:
    # A value that merely looks like a delimiter or another field must not collide.
    one = helper.compute_request_fingerprint("op", {"a": "1,\"b\":\"2", "b": None})
    two = helper.compute_request_fingerprint("op", {"a": "1", "b": "2"})

    assert one != two


@pytest.mark.parametrize("bad", [1.5, Decimal("1.00"), UUID(int=1), [1], {"a": 1}])
def test_values_without_a_canonical_form_are_rejected(bad: object) -> None:
    with pytest.raises(TypeError):
        helper.compute_request_fingerprint("op", {"field": bad})  # type: ignore[dict-item]


def test_lock_key_has_a_fixed_known_vector_and_fits_bigint() -> None:
    key = helper.compute_create_key_lock_key("income.create", USER, KEY)

    assert key == -2447506956305372575
    assert -(2 ** 63) <= key < 2 ** 63


def test_lock_key_separates_operation_user_and_key_and_is_deterministic() -> None:
    base = helper.compute_create_key_lock_key("income.create", USER, KEY)

    assert helper.compute_create_key_lock_key("income.create", USER, KEY) == base
    assert helper.compute_create_key_lock_key("expense.create", USER, KEY) != base
    assert helper.compute_create_key_lock_key("income.create", UUID(int=9), KEY) != base
    assert helper.compute_create_key_lock_key("income.create", USER, UUID(int=9)) != base
