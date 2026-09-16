from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_service, budget_version_repository
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetUpdate
from app.modules.budgets.budget_version_models import BudgetVersionModel
from app.modules.categories import service as categories_service
from app.modules.categories.schemas import CategoryCreate


def _versions_for_budget(db_session, budget_id):
    return (
        db_session.query(BudgetVersionModel)
        .filter(BudgetVersionModel.budget_id == budget_id)
        .order_by(BudgetVersionModel.created_at)
        .all()
    )


# Tests that creating a budget writes exactly one 'initial' version.
# This test exists to lock in the Part 3 invariant: every budget has a
# version history from the moment it exists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one 'initial' version is created.
def test_create_budget_creates_exactly_one_initial_version(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
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

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        assert len(versions) == 1
        assert versions[0].change_reason == "initial"
        assert versions[0].effective_from == date(2026, 5, 1)
        assert versions[0].effective_until is None
        assert versions[0].limit_amount == Decimal("400.00")
        assert isinstance(versions[0].limit_amount, Decimal)
        assert versions[0].category_id is None
        assert versions[0].user_id == user_id
    finally:
        db_session.close()


# Tests that editing a budget's limit appends a new version without
# touching the prior one.
# This test exists to verify the core append-only guarantee: history must
# never be rewritten, only added to.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if two versions exist and the first is unchanged.
def test_update_budget_limit_change_appends_version_prior_untouched(
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
        initial_version_id = _versions_for_budget(db_session, budget.id)[0].id

        # Act
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("600")),
            user_id=user_id,
        )

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        assert len(versions) == 2

        prior_version = next(v for v in versions if v.id == initial_version_id)
        assert prior_version.limit_amount == Decimal("500.00")
        assert prior_version.effective_from == date(2026, 5, 1)

        new_version = next(v for v in versions if v.id != initial_version_id)
        assert new_version.limit_amount == Decimal("600.00")
        assert new_version.change_reason == "user_edit"
        assert new_version.effective_from == date.today().replace(day=1)
    finally:
        db_session.close()


# Tests that two limit edits within the same period both persist as
# separate rows, and the resolver picks the later one by created_at.
# This test exists because versions are never UPSERTed - the audit trail
# is the point, per Part 4.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both rows exist and the resolver returns the
#   most recently created one.
def test_update_budget_two_edits_same_period_both_persist_resolver_picks_latest(
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

        # Act
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("600")),
            user_id=user_id,
        )
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("700")),
            user_id=user_id,
        )

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        # initial + two user_edit rows at the same effective_from
        assert len(versions) == 3

        current_period_start = date.today().replace(day=1)
        resolved = budget_version_repository.resolve_version_for_period(
            db_session=db_session,
            budget_id=budget.id,
            period_start=current_period_start,
            period_end=current_period_start,
        )
        assert resolved is not None
        assert resolved.limit_amount == Decimal("700.00")
    finally:
        db_session.close()


# Tests that resolving a past period returns the limit that was in effect
# at the time, not the budget's current limit.
# This test exists as the core history test: it is the entire reason
# budget_versions exists rather than reading budgets.limit_amount directly.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the past period resolves the original limit.
def test_resolve_version_for_period_returns_old_limit_for_past_period(
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

        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("600")),
            user_id=user_id,
        )

        # Act: resolve the original May 2026 period, long before the edit.
        resolved = budget_version_repository.resolve_version_for_period(
            db_session=db_session,
            budget_id=budget.id,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )

        # Assert
        assert resolved is not None
        assert resolved.limit_amount == Decimal("500.00")
        assert resolved.change_reason == "initial"
    finally:
        db_session.close()


# Tests that resolving a period before the budget's first version returns
# no match.
# This test exists to document the resolver's behavior for an ambiguous/
# out-of-range query rather than leaving it undefined.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if resolve_version_for_period returns None.
def test_resolve_version_for_period_returns_none_before_first_version(
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

        # Act: a period entirely before the budget's activation.
        resolved = budget_version_repository.resolve_version_for_period(
            db_session=db_session,
            budget_id=budget.id,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )

        # Assert
        assert resolved is None
    finally:
        db_session.close()


# Tests that changing a budget's category appends a version carrying the
# new category, while a past period still resolves the old category scope.
# This test exists to verify Part 5's "freeze category identity" property:
# historical scope must not change when a budget is re-scoped today.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the past period resolves the original category
#   and the new version carries the new one.
def test_update_budget_category_change_appends_version_past_period_resolves_old(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        original_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Food"),
            user_id=user_id,
        )
        new_category = categories_service.create_category(
            db_session=db_session,
            category_data=CategoryCreate(name="Dining out"),
            user_id=user_id,
        )

        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=BudgetCreate(
                category_id=original_category.id,
                name="Groceries",
                limit_amount=Decimal("500"),
                currency="EUR",
                period="monthly",
                start_date=date(2026, 5, 1),
                end_date=None,
            ),
            user_id=user_id,
        )

        # Act
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(category_id=new_category.id),
            user_id=user_id,
        )

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        assert len(versions) == 2
        latest_version = max(versions, key=lambda v: v.created_at)
        assert latest_version.category_id == new_category.id
        assert latest_version.change_reason == "category_change"

        past_period_version = budget_version_repository.resolve_version_for_period(
            db_session=db_session,
            budget_id=budget.id,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
        assert past_period_version is not None
        assert past_period_version.category_id == original_category.id
    finally:
        db_session.close()


# Tests that updating a non-versioned field (name) does not create an
# unnecessary version row.
# This test exists to verify that only limit_amount/category_id changes
# trigger history writes - the version table must not grow on every PATCH.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the version count stays at one.
def test_update_budget_non_versioned_field_does_not_create_version(
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

        # Act
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(name="Groceries and household"),
            user_id=user_id,
        )

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        assert len(versions) == 1
    finally:
        db_session.close()


# Tests that setting limit_amount to its current value (a no-op edit) does
# not create a new version.
# This test exists because model_fields_set only tells us the field was
# sent, not that it changed - a no-op PATCH must not pollute history.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the version count stays at one.
def test_update_budget_unchanged_limit_amount_does_not_create_version(
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

        # Act
        budget_service.update_budget(
            db_session=db_session,
            budget_id=budget.id,
            budget_data=BudgetUpdate(limit_amount=Decimal("500")),
            user_id=user_id,
        )

        # Assert
        versions = _versions_for_budget(db_session, budget.id)
        assert len(versions) == 1
    finally:
        db_session.close()
