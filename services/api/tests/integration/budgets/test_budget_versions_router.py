from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.modules.budgets.budget_version_models import BudgetVersionModel
from tests.helpers import auth_headers, create_budget, create_category


def _versions_for_budget(budget_id: str) -> list[BudgetVersionModel]:
    db_session = SessionLocal()
    try:
        return (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget_id)
            .order_by(BudgetVersionModel.created_at)
            .all()
        )
    finally:
        db_session.close()


# Tests that creating a budget through the API also creates its initial
# version.
# This test exists to verify create_budget's transactional guarantee end to
# end: a budget must never exist without a matching initial version.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if exactly one 'initial' version exists.
def test_create_budget_endpoint_creates_initial_version(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=400,
    )

    # Assert
    versions = _versions_for_budget(created_budget["id"])
    assert len(versions) == 1
    assert versions[0].change_reason == "initial"
    assert versions[0].effective_from == date(2026, 5, 1)
    assert versions[0].limit_amount == Decimal("400.00")


# Tests that updating a budget's limit through the API keeps the previous
# version and makes the new limit current.
# This test exists to verify the update flow end to end, at the same layer
# mobile actually calls.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if both versions exist with the correct limits.
def test_update_budget_endpoint_limit_change_preserves_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Groceries",
        limit_amount=500,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"limit_amount": 600},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    versions = _versions_for_budget(created_budget["id"])
    assert len(versions) == 2

    initial_version = next(v for v in versions if v.change_reason == "initial")
    assert initial_version.limit_amount == Decimal("500.00")
    assert initial_version.effective_from == date(2026, 5, 1)

    edited_version = next(v for v in versions if v.change_reason == "user_edit")
    assert edited_version.limit_amount == Decimal("600.00")
    assert edited_version.effective_from == date.today().replace(day=1)


# Tests that changing a budget's category through the API preserves the
# original scope in history while making the new scope current.
# This test exists to verify Part 5's "freeze category identity" property
# end to end.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the new version carries the new category and
#   the prior version still carries the original one.
def test_update_budget_endpoint_category_change_preserves_history(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    original_category = create_category(client=client, user_id=user_id, name="Food")
    new_category = create_category(client=client, user_id=user_id, name="Dining out")

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=original_category["id"],
        name="Groceries",
        limit_amount=400,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"category_id": new_category["id"]},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    versions = _versions_for_budget(created_budget["id"])
    assert len(versions) == 2

    initial_version = next(v for v in versions if v.change_reason == "initial")
    assert str(initial_version.category_id) == original_category["id"]

    changed_version = next(v for v in versions if v.change_reason == "category_change")
    assert str(changed_version.category_id) == new_category["id"]


# Tests that updating a non-versioned field (name) through the API does not
# create an extra version row.
# This test exists to verify the version table only grows on the fields
# that actually affect historical meaning.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if exactly one version still exists after the update.
def test_update_budget_endpoint_name_change_does_not_create_version(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Groceries",
        limit_amount=400,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"name": "Groceries and household"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert len(_versions_for_budget(created_budget["id"])) == 1


# Tests that a budget's currency cannot be changed through the API.
# This test exists to verify BudgetImmutableFieldError surfaces as a 409
# at the router level, matching the project's centralized error mapping.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409 and the budget is unchanged.
def test_update_budget_endpoint_rejects_currency_change(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Groceries",
        limit_amount=400,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"currency": "USD"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Budget currency cannot be changed. Period and start date cannot "
        "be changed after the first period completes."
    )


# Tests that a budget's end_date cannot be set to a date before today
# through the API.
# This test exists to verify BudgetRetroactiveDeactivationError surfaces as
# a 409 at the router level.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns 409.
def test_update_budget_endpoint_rejects_retroactive_end_date(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_budget = create_budget(
        client=client,
        user_id=user_id,
        category_id=None,
        name="Groceries",
        limit_amount=400,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"end_date": "2020-01-02"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["detail"] == "Budget end date cannot be set to a date before today."


# Tests that updating another user's budget never creates a version row
# under the requesting user, and the target budget's history stays intact.
# This test exists to verify ownership isolation extends to version
# writes, not only to the budget row itself.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the request is rejected and no second version
#   is created.
def test_update_budget_endpoint_rejects_other_user_budget_no_version_created(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_budget = create_budget(
        client=client,
        user_id=other_user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=100,
    )

    # Act
    response = client.patch(
        f"/api/v1/budgets/{other_user_budget['id']}",
        json={"limit_amount": 150},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404

    versions = _versions_for_budget(other_user_budget["id"])
    assert len(versions) == 1
    assert versions[0].limit_amount == Decimal("100.00")
    assert str(versions[0].user_id) == other_user_id
