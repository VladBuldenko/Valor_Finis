from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_service import _build_goal_response
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# VF-020C2 unit tests that need no database: the request validator and the
# Goal read-model builder.


# Tests that account_id without client_request_id is rejected, for both
# types, while explicit null account_id needs no key.
@pytest.mark.parametrize("kind", ["contribution", "withdrawal"])
def test_linked_request_requires_key(kind: str) -> None:
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type=kind, amount=Decimal("1"), account_id=uuid4())

    assert GoalTransactionCreate(type=kind, amount=Decimal("1"), account_id=None).account_id is None
    assert GoalTransactionCreate(
        type=kind, amount=Decimal("1"), account_id=uuid4(), client_request_id=uuid4(),
    ).account_id is not None


# Tests extra fields are still forbidden (user_id never comes from the body).
def test_extra_fields_still_forbidden() -> None:
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("1"), user_id=str(uuid4()))


def _goal() -> GoalModel:
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    return GoalModel(
        id=uuid4(), user_id=uuid4(), name="G", target_amount=Decimal("100"), currency="EUR",
        target_date=None, status="active", created_at=now, updated_at=now,
    )


# Tests the builder: tracked/linked/current arithmetic, zero partitions are
# hidden, allocations are ordered by account_id, amounts stay Decimal.
def test_build_goal_response_partitions() -> None:
    low = UUID("00000000-0000-0000-0000-000000000001")
    high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    zero = UUID("00000000-0000-0000-0000-000000000002")

    response = _build_goal_response(
        _goal(),
        {None: Decimal("10.00"), high: Decimal("5.50"), low: Decimal("2.25"), zero: Decimal("0.00")},
    )

    assert response.tracked_amount == Decimal("10.00")
    assert response.linked_amount == Decimal("7.75")
    assert response.current_amount == Decimal("17.75")
    assert [item.account_id for item in response.allocations] == [low, high]
    assert all(isinstance(item.amount, Decimal) for item in response.allocations)


# Tests a goal without any partition is all zeros.
def test_build_goal_response_empty() -> None:
    response = _build_goal_response(_goal(), {})

    assert response.current_amount == response.tracked_amount == response.linked_amount == Decimal("0.00")
    assert response.allocations == []
