from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_service
from app.modules.budgets.budget_errors import (
    BudgetImmutableFieldError,
    BudgetRetroactiveDeactivationError,
)
from app.modules.budgets.budget_period import resolve_period
from app.modules.budgets.budget_schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
)
from app.modules.budgets.budget_version_models import BudgetVersionModel
from app.modules.categories import service as categories_service
from app.modules.categories.errors import CategoryNotFoundError
from app.modules.categories.schemas import CategoryCreate


# Tests that the service creates a budget and returns a response schema.
# This test exists to verify that the service layer maps database models to API responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created budget response contains the expected values.
def test_create_budget_returns_budget_response(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
        )

        # Assert
        assert isinstance(budget, BudgetResponse)
        assert budget.user_id == user_id
        assert budget.category_id is None
        assert budget.name == budget_data.name
        assert budget.limit_amount == Decimal("400")
        assert budget.currency == budget_data.currency
        assert budget.period == budget_data.period
        assert budget.start_date == budget_data.start_date
        assert budget.end_date is None
        assert budget.id is not None
        assert budget.created_at is not None
        assert budget.updated_at is not None
    finally:
        db_session.close()


# Tests that the service returns budgets for a specific user.
# This test exists to verify that the service layer provides user-scoped budget responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the service returns only the requested user's budgets.
def test_get_budgets_returns_user_budget_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    other_user_budget_data = BudgetCreate(
        category_id=None,
        name="Transport budget",
        limit_amount=Decimal("150"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        budget_service.create_budget(
            db_session=db_session,
            budget_data=user_budget_data,
            user_id=user_id,
        )
        budget_service.create_budget(
            db_session=db_session,
            budget_data=other_user_budget_data,
            user_id=other_user_id,
        )

        # Act
        budgets = budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(budgets) == 1
        assert isinstance(budgets[0], BudgetResponse)
        assert budgets[0].user_id == user_id
        assert budgets[0].category_id is None
        assert budgets[0].name == user_budget_data.name
        assert budgets[0].limit_amount == Decimal("400")
        assert budgets[0].currency == user_budget_data.currency
        assert budgets[0].period == user_budget_data.period
        assert budgets[0].start_date == user_budget_data.start_date
        assert budgets[0].end_date is None
    finally:
        db_session.close()


# Tests that a budget can be created with a category owned by the same user.
# This test exists to verify the happy path of category ownership validation
# during budget creation.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created budget references the owned category.
def test_create_budget_allows_authenticated_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=user_id,
        )

        budget_data = BudgetCreate(
            category_id=category.id,
            name="Food budget",
            limit_amount=Decimal("400"),
            currency="EUR",
            period="monthly",
            start_date=date(2026, 5, 1),
            end_date=None,
        )

        # Act
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
        )

        # Assert
        assert budget.category_id == category.id
    finally:
        db_session.close()


# Tests that a budget cannot be created with another user's category.
# This test exists to prevent cross-user category assignment during creation.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_create_budget_rejects_other_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_user_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=other_user_id,
        )

        budget_data = BudgetCreate(
            category_id=other_user_category.id,
            name="Food budget",
            limit_amount=Decimal("400"),
            currency="EUR",
            period="monthly",
            start_date=date(2026, 5, 1),
            end_date=None,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.create_budget(
                db_session=db_session,
                budget_data=budget_data,
                user_id=user_id,
            )

        assert budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        ) == []
    finally:
        db_session.close()


# Tests that a budget cannot be created with a category id that does not exist.
# This test exists to return a controlled domain error instead of relying
# only on a database foreign key failure.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_create_budget_rejects_nonexistent_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
        category_id=uuid4(),
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.create_budget(
                db_session=db_session,
                budget_data=budget_data,
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a budget can be updated to reference a category owned by the same user.
# This test exists to verify the happy path of category ownership validation
# during budget updates.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the updated budget references the owned category.
def test_update_budget_allows_authenticated_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=user_id,
        )

        # Act
        updated_budget = budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(category_id=category.id),
            user_id=user_id,
        )

        # Assert
        assert updated_budget.category_id == category.id
    finally:
        db_session.close()


# Tests that a budget cannot be updated to reference another user's category.
# This test exists to prevent cross-user category assignment during updates.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised and the budget's
#   category is left unchanged.
def test_update_budget_rejects_other_user_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        other_user_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=other_user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(category_id=other_user_category.id),
                user_id=user_id,
            )

        budgets = budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )
        assert budgets[0].category_id is None
    finally:
        db_session.close()


# Tests that a budget cannot be updated to reference a category id that does
# not exist.
# This test exists to return a controlled domain error instead of relying
# only on a database foreign key failure.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if CategoryNotFoundError is raised.
def test_update_budget_rejects_nonexistent_category(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(CategoryNotFoundError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(category_id=uuid4()),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that updating a budget without setting category_id does not trigger
# a category ownership lookup.
# This test exists to verify that omitted fields are left untouched and do
# not cause unnecessary category service calls.
# Parameters:
# - monkeypatch: pytest fixture used to observe categories_service calls.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if categories_service.get_category_by_id is never called.
def test_update_budget_skips_category_lookup_when_category_id_omitted(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    category_lookup_calls: list[UUID] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> None:
        category_lookup_calls.append(category_id)

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        monkeypatch.setattr(
            budget_service.categories_service,
            "get_category_by_id",
            fake_get_category_by_id,
        )

        # Act
        updated_budget = budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("500")),
            user_id=user_id,
        )

        # Assert
        assert updated_budget.limit_amount == Decimal("500")
        assert category_lookup_calls == []
    finally:
        db_session.close()


# Tests that a budget's currency can never be changed.
# This test exists to lock in Part 4: re-denominating a limit changes the
# real value it represents, so currency is rejected regardless of lifecycle
# state, unlike period/start_date which have a typo-fix window.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if BudgetImmutableFieldError is raised.
def test_update_budget_rejects_currency_change(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(BudgetImmutableFieldError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(currency="USD"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a budget's period cannot be changed once its first period has
# completed.
# This test exists to lock in Part 4: changing period after periods have
# already occurred would make those periods non-reconstructible. Uses a
# start_date far in the past so the check is robust to wall-clock drift.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if BudgetImmutableFieldError is raised.
def test_update_budget_rejects_period_change_after_first_period_completed(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2020, 1, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(BudgetImmutableFieldError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(period="weekly"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a budget's start_date cannot be changed once its first period
# has completed.
# This test exists as the start_date counterpart to the period guard above.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if BudgetImmutableFieldError is raised.
def test_update_budget_rejects_start_date_change_after_first_period_completed(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2020, 1, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(BudgetImmutableFieldError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(start_date=date(2020, 1, 15)),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that period/start_date can still be corrected while the budget is
# still within its first, not-yet-completed period (the typo-fix window),
# and that doing so replaces rather than appends to the version history.
# This test exists to verify the pre-first-period-completion exception to
# the immutability guard, and the DEVIATION 2 replace-history behavior for
# it. Uses today as start_date so the budget is always within its own
# first period regardless of wall-clock drift.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the update succeeds and exactly one 'initial'
#   version remains, reflecting the corrected definition.
def test_update_budget_allows_period_change_within_first_period(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    today = date.today()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=today,
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act
        updated_budget = budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(period="weekly"),
            user_id=user_id,
        )

        # Assert
        assert updated_budget.period == "weekly"

        versions = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget.id)
            .all()
        )
        assert len(versions) == 1
        assert versions[0].change_reason == "initial"
        assert versions[0].effective_from == resolve_period("weekly", today).period_start
        assert versions[0].limit_amount == Decimal("400.00")
    finally:
        db_session.close()


# Tests that a budget's end_date cannot be set to a date before today.
# This test exists to lock in Part 4: retroactively deactivating a budget
# would erase already-completed periods that were counted against it.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if BudgetRetroactiveDeactivationError is raised.
def test_update_budget_rejects_retroactive_end_date(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=date(2020, 1, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act / Assert
        with pytest.raises(BudgetRetroactiveDeactivationError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(end_date=date(2020, 1, 2)),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a failure writing the initial version rolls back the budget
# row too, so no budget can ever exist without its initial version.
# This test exists to prove the atomicity invariant, not just assert it:
# forces a failure in the version-write step after the budget row has
# already been prepared (flushed) and confirms neither row survives.
# Parameters:
# - monkeypatch: pytest fixture used to force create_version to fail.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the exception propagates and nothing persists.
def test_create_budget_rolls_back_when_version_write_fails(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    def fake_create_version(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated version write failure")

    monkeypatch.setattr(
        budget_service.budget_version_repository,
        "create_version",
        fake_create_version,
    )

    budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act / Assert
        with pytest.raises(RuntimeError):
            budget_service.create_budget(
                db_session=db_session,
                budget_data=budget_data,
                user_id=user_id,
            )

        # Assert: neither the budget nor any version was persisted.
        remaining_budgets = (
            db_session.query(budget_service.BudgetModel)
            .filter(budget_service.BudgetModel.user_id == user_id)
            .all()
        )
        assert remaining_budgets == []

        remaining_versions = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.user_id == user_id)
            .all()
        )
        assert remaining_versions == []
    finally:
        db_session.close()


# Tests that a failure writing a new version during a limit change rolls
# back the budget row's limit_amount too, leaving both the budget and its
# history exactly as they were before the update.
# This test exists to prove update_budget's atomicity for the common
# limit/category-edit path, not only the create path.
# Parameters:
# - monkeypatch: pytest fixture used to force create_version to fail.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the exception propagates, the budget keeps its
#   original limit, and no partial new version exists.
def test_update_budget_limit_change_rolls_back_on_version_write_failure(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Groceries",
                limit_amount=Decimal("500"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        original_versions = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget.id)
            .all()
        )
        assert len(original_versions) == 1
        original_version_id = original_versions[0].id

        def fake_create_version(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated version write failure")

        monkeypatch.setattr(
            budget_service.budget_version_repository,
            "create_version",
            fake_create_version,
        )

        # Act / Assert
        with pytest.raises(RuntimeError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(limit_amount=Decimal("600")),
                user_id=user_id,
            )

        # Assert: budget keeps its previous persisted limit.
        persisted_budget = (
            db_session.query(budget_service.BudgetModel)
            .filter(budget_service.BudgetModel.id == budget.id)
            .first()
        )
        assert persisted_budget.limit_amount == Decimal("500.00")

        # Assert: previous history intact, no partial new version.
        versions_after = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget.id)
            .all()
        )
        assert len(versions_after) == 1
        assert versions_after[0].id == original_version_id
        assert versions_after[0].limit_amount == Decimal("500.00")
    finally:
        db_session.close()


# Tests that a failure during the period/start_date history-replace flow
# rolls back both the budget row's period change and the version-history
# delete that had already run in the same transaction.
# This test exists to prove atomicity for the multi-step replace path
# specifically: delete_versions_for_budget succeeds (flushed) and then
# create_version fails, simulating a failure after part of the operation.
# Parameters:
# - monkeypatch: pytest fixture used to force create_version to fail.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the exception propagates, the budget keeps its
#   original period, and the original version row survives unchanged.
def test_update_budget_period_reset_rolls_back_on_failure_after_partial_delete(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    today = date.today()

    try:
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=None,
                name="Food budget",
                limit_amount=Decimal("400"),
                currency="EUR",
                period="monthly",
                start_date=today,
                end_date=None,
            ),
            user_id=user_id,
        )

        original_versions = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget.id)
            .all()
        )
        assert len(original_versions) == 1
        original_version_id = original_versions[0].id

        def fake_create_version(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated failure after delete_versions_for_budget")

        monkeypatch.setattr(
            budget_service.budget_version_repository,
            "create_version",
            fake_create_version,
        )

        # Act / Assert
        with pytest.raises(RuntimeError):
            budget_service.update_budget(
                db_session=db_session,
                budget_id=budget.id,
                budget_data=BudgetUpdate(period="weekly"),
                user_id=user_id,
            )

        # Assert: budget keeps its original period - the update was rolled
        # back even though it had already been flushed.
        persisted_budget = (
            db_session.query(budget_service.BudgetModel)
            .filter(budget_service.BudgetModel.id == budget.id)
            .first()
        )
        assert persisted_budget.period == "monthly"

        # Assert: the original version survives untouched - the delete that
        # had already run (flushed) was rolled back along with everything else.
        versions_after = (
            db_session.query(BudgetVersionModel)
            .filter(BudgetVersionModel.budget_id == budget.id)
            .all()
        )
        assert len(versions_after) == 1
        assert versions_after[0].id == original_version_id
    finally:
        db_session.close()