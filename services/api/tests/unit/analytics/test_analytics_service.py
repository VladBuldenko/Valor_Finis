from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from typing import Optional, cast
from sqlalchemy.orm import Session
from pytest import MonkeyPatch

from app.db.database_session import SessionLocal
from app.modules.analytics import analytics_service
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetUpdate

# Creates a simple object with dynamic attributes.
# This helper exists to imitate SQLAlchemy models without using the database.
# Parameters:
# - kwargs: field names and values for the fake model.
# Returns:
# - SimpleNamespace object with provided attributes.
def make_model(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


# Mocks financial_settings_service.get_base_currency so monthly/category
# summary tests never touch a real database session.
# Parameters:
# - monkeypatch: pytest fixture used to replace the service call.
# - base_currency: the currency value the fake should return.
# Returns:
# - None.
def wire_base_currency(monkeypatch: MonkeyPatch, base_currency: str = "EUR") -> None:
    monkeypatch.setattr(
        analytics_service.financial_settings_service,
        "get_base_currency",
        lambda db_session, user_id: base_currency,
    )


# Creates a fake Expense with VF-014B5C FX snapshot fields, for monthly/
# category summary tests.
# This helper exists to keep those test bodies focused on the resolved/
# unresolved/incompatible scenario being asserted.
# Parameters:
# - amount/currency: original transaction truth.
# - expense_date: expense date, used for time filtering.
# - category_id: optional category.
# - base_amount/base_currency: resolved base-currency snapshot; both None
#   together represents a legacy unresolved Expense.
# Returns:
# - SimpleNamespace imitating an ExpenseModel.
def make_summary_expense(
    amount: Decimal,
    currency: str = "EUR",
    expense_date: date = date(2026, 5, 7),
    category_id=None,
    base_amount: Optional[Decimal] = None,
    base_currency: Optional[str] = None,
) -> SimpleNamespace:
    return make_model(
        amount=amount,
        currency=currency,
        expense_date=expense_date,
        category_id=category_id,
        base_amount=base_amount,
        base_currency=base_currency,
    )


# ---------------------------------------------------------------------------
# get_monthly_summary (VF-014B5D base-currency spending)
# ---------------------------------------------------------------------------


# Tests (A) zero Expenses and (I) that base_currency is still returned.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if all fields reflect a safe empty state.
def test_get_monthly_summary_zero_expenses_returns_base_currency(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: [],
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("0")
    assert summary.expenses_count == 0
    assert summary.unresolved_expenses_count == 0
    assert summary.base_currency == "EUR"


# Tests (B) a single resolved EUR Expense.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if total_spent/expenses_count reflect it.
def test_get_monthly_summary_one_resolved_eur_expense(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    expenses = [
        make_summary_expense(
            amount=Decimal("24.99"), base_amount=Decimal("24.99"), base_currency="EUR",
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("24.99")
    assert summary.expenses_count == 1


# Tests (C, D) that a resolved EUR Expense and a resolved USD-original
# Expense are summed by base_amount, not original amount - the task's own
# worked example (100 EUR + 100 USD-original/84.73 EUR-base -> 184.73, not
# 200). This value is deliberately chosen so the test fails if the
# implementation regresses to summing expense.amount.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes only if total_spent == 184.73.
def test_get_monthly_summary_sums_base_amount_not_original_amount(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    expenses = [
        make_summary_expense(
            amount=Decimal("100.00"), currency="EUR",
            base_amount=Decimal("100.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("100.00"), currency="USD",
            base_amount=Decimal("84.73"), base_currency="EUR",
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("184.73")
    assert summary.total_spent != Decimal("200.00")
    assert summary.expenses_count == 2


# Tests (E, F, G) that a legacy unresolved Expense (base_amount is None)
# is excluded from total_spent, counted separately in
# unresolved_expenses_count, and never counted in expenses_count.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the unresolved row does not affect the total
#   or the resolved count, but is visible in unresolved_expenses_count.
def test_get_monthly_summary_excludes_unresolved_legacy_expense(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    expenses = [
        make_summary_expense(
            amount=Decimal("50.00"), base_amount=Decimal("50.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("999.00"), currency="USD",
            base_amount=None, base_currency=None,  # legacy unresolved
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("50.00")
    assert summary.expenses_count == 1
    assert summary.unresolved_expenses_count == 1


# Tests (H) that existing month-filtering behavior is unchanged: an
# expense outside the selected year/month is excluded regardless of its
# resolution state.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the May expense is counted.
def test_get_monthly_summary_filters_by_selected_month(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    expenses = [
        make_summary_expense(
            amount=Decimal("20.00"), expense_date=date(2026, 5, 7),
            base_amount=Decimal("20.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("999.00"), expense_date=date(2026, 6, 7),
            base_amount=Decimal("999.00"), base_currency="EUR",
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("20.00")
    assert summary.expenses_count == 1


# Tests (J) that a resolved Expense whose persisted base_currency does not
# match the user's current base_currency is treated safely: excluded from
# total_spent and counted as unresolved/incompatible, never summed as if
# it were in the right currency.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the incompatible row is excluded and counted.
def test_get_monthly_summary_incompatible_base_currency_excluded_and_counted(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")
    expenses = [
        make_summary_expense(
            amount=Decimal("50.00"), base_amount=Decimal("50.00"), base_currency="EUR",
        ),
        make_summary_expense(
            # Resolved, but persisted against a different base_currency
            # than the user's current one - not reachable today (base
            # currency mutation is not exposed), but must fail safely.
            amount=Decimal("999.00"), base_amount=Decimal("900.00"), base_currency="USD",
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )

    # Act
    summary = analytics_service.get_monthly_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert summary.total_spent == Decimal("50.00")
    assert summary.expenses_count == 1
    assert summary.unresolved_expenses_count == 1


# ---------------------------------------------------------------------------
# get_category_summary (VF-014B5D base-currency spending)
# ---------------------------------------------------------------------------


# Tests (A, B, C, F, I) that resolved mixed-original-currency Expenses in
# the same category (and Uncategorized) are summed by base_amount, with
# correct resolved counts and base_currency on every item.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if category totals/counts/base_currency match.
def test_get_category_summary_sums_base_amount_by_category(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    categories = [make_model(id=food_category_id, name="Food")]
    expenses = [
        make_summary_expense(
            amount=Decimal("20.00"), currency="EUR", category_id=food_category_id,
            base_amount=Decimal("20.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("30.00"), currency="USD", category_id=food_category_id,
            base_amount=Decimal("25.50"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("15.00"), category_id=None,
            base_amount=Decimal("15.00"), base_currency="EUR",
        ),
    ]

    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id,
    )
    by_id = {item.category_id: item for item in category_summary}

    # Assert
    assert len(category_summary) == 2

    assert by_id[food_category_id].category_name == "Food"
    assert by_id[food_category_id].total_spent == Decimal("45.50")
    assert by_id[food_category_id].total_spent != Decimal("50.00")
    assert by_id[food_category_id].expenses_count == 2
    assert by_id[food_category_id].unresolved_expenses_count == 0
    assert by_id[food_category_id].base_currency == "EUR"

    # (F) Uncategorized resolved
    assert by_id[None].category_name == "Uncategorized"
    assert by_id[None].total_spent == Decimal("15.00")
    assert by_id[None].expenses_count == 1
    assert by_id[None].base_currency == "EUR"


# Tests (D, E) that a category containing matching Expenses which are ALL
# unresolved is still returned (never silently omitted), with
# total_spent=0, expenses_count=0, and unresolved_expenses_count > 0.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the unresolved-only category is present.
def test_get_category_summary_unresolved_only_category_still_returned(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    legacy_category_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    categories = [make_model(id=legacy_category_id, name="Legacy")]
    expenses = [
        make_summary_expense(
            amount=Decimal("40.00"), currency="USD", category_id=legacy_category_id,
            base_amount=None, base_currency=None,
        ),
        make_summary_expense(
            amount=Decimal("10.00"), currency="USD", category_id=legacy_category_id,
            base_amount=None, base_currency=None,
        ),
    ]

    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id,
    )

    # Assert
    assert len(category_summary) == 1
    item = category_summary[0]
    assert item.category_id == legacy_category_id
    assert item.category_name == "Legacy"
    assert item.total_spent == Decimal("0")
    assert item.expenses_count == 0
    assert item.unresolved_expenses_count == 2


# Tests (G) that an unresolved Uncategorized Expense increments the
# Uncategorized item's unresolved_expenses_count without affecting its
# total_spent.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if Uncategorized reflects one resolved and one
#   unresolved expense correctly.
def test_get_category_summary_uncategorized_unresolved(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    expenses = [
        make_summary_expense(
            amount=Decimal("15.00"), category_id=None,
            base_amount=Decimal("15.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("999.00"), currency="USD", category_id=None,
            base_amount=None, base_currency=None,
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: [],
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id,
    )

    # Assert
    assert len(category_summary) == 1
    item = category_summary[0]
    assert item.category_id is None
    assert item.category_name == "Uncategorized"
    assert item.total_spent == Decimal("15.00")
    assert item.expenses_count == 1
    assert item.unresolved_expenses_count == 1


# Tests (H) that optional year/month filtering behavior is unchanged.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the May expenses are counted.
def test_get_category_summary_filters_by_selected_month(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    categories = [make_model(id=food_category_id, name="Food")]
    expenses = [
        make_summary_expense(
            amount=Decimal("20.00"), expense_date=date(2026, 5, 7), category_id=food_category_id,
            base_amount=Decimal("20.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("30.00"), expense_date=date(2026, 5, 20), category_id=food_category_id,
            base_amount=Decimal("30.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("70.00"), expense_date=date(2026, 6, 7), category_id=food_category_id,
            base_amount=Decimal("70.00"), base_currency="EUR",
        ),
    ]

    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id, year=2026, month=5,
    )

    # Assert
    assert len(category_summary) == 1
    assert category_summary[0].category_id == food_category_id
    assert category_summary[0].category_name == "Food"
    assert category_summary[0].total_spent == Decimal("50.00")
    assert category_summary[0].expenses_count == 2


# Tests (I) that multiple categories are each computed and returned
# independently.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if both categories have correct independent totals.
def test_get_category_summary_multiple_categories_independent(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    transport_category_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    categories = [
        make_model(id=food_category_id, name="Food"),
        make_model(id=transport_category_id, name="Transport"),
    ]
    expenses = [
        make_summary_expense(
            amount=Decimal("20.00"), category_id=food_category_id,
            base_amount=Decimal("20.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("40.00"), category_id=transport_category_id,
            base_amount=Decimal("40.00"), base_currency="EUR",
        ),
    ]

    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id,
    )
    by_id = {item.category_id: item for item in category_summary}

    # Assert
    assert by_id[food_category_id].total_spent == Decimal("20.00")
    assert by_id[transport_category_id].total_spent == Decimal("40.00")


# Tests (K) that a resolved Expense whose persisted base_currency does not
# match the user's current base_currency is excluded from the category
# total and counted as unresolved, never silently summed.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the incompatible row is excluded and counted.
def test_get_category_summary_incompatible_base_currency_excluded_and_counted(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    categories = [make_model(id=food_category_id, name="Food")]
    expenses = [
        make_summary_expense(
            amount=Decimal("20.00"), category_id=food_category_id,
            base_amount=Decimal("20.00"), base_currency="EUR",
        ),
        make_summary_expense(
            amount=Decimal("999.00"), category_id=food_category_id,
            base_amount=Decimal("900.00"), base_currency="USD",
        ),
    ]
    monkeypatch.setattr(
        analytics_service.expenses_repository, "get_expenses", lambda **kwargs: expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository, "get_categories", lambda **kwargs: categories,
    )

    # Act
    category_summary = analytics_service.get_category_summary(
        db_session=db_session, user_id=user_id,
    )

    # Assert
    assert len(category_summary) == 1
    item = category_summary[0]
    assert item.total_spent == Decimal("20.00")
    assert item.expenses_count == 1
    assert item.unresolved_expenses_count == 1

# ---------------------------------------------------------------------------
# get_budget_status (VF-014B3 calendar-period semantics)
# ---------------------------------------------------------------------------


def make_budget(
    id=None,
    name: str = "Budget",
    period: str = "monthly",
    currency: str = "EUR",
    start_date: date = date(2026, 9, 1),
    end_date=None,
) -> SimpleNamespace:
    return make_model(
        id=id or uuid4(),
        name=name,
        period=period,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
    )


def make_version(
    limit_amount: Decimal = Decimal("100.00"),
    category_id=None,
) -> SimpleNamespace:
    return make_model(limit_amount=limit_amount, category_id=category_id)


def make_expense(
    amount: Decimal,
    expense_date: date,
    category_id=None,
    currency: str = "EUR",
) -> SimpleNamespace:
    return make_model(
        amount=amount,
        expense_date=expense_date,
        category_id=category_id,
        currency=currency,
    )


# Wires up get_budgets/get_expenses/get_categories/resolve_version_for_period
# fakes for a single-budget scenario.
# This helper exists to keep the individual test bodies focused on the
# scenario being asserted rather than repeated monkeypatch wiring.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# - budget: the single fake budget under test.
# - expenses: fake expenses visible to the calculation.
# - version: the fake BudgetVersion the resolver should return.
# - categories: fake categories for name resolution (default none).
# Returns:
# - list[tuple] capturing every (budget_id, period_start, period_end) the
#   resolver was called with, so a test can assert the exact period resolved.
def wire_budget_status_deps(
    monkeypatch: MonkeyPatch,
    budget: SimpleNamespace,
    expenses: list,
    version: SimpleNamespace,
    categories: Optional[list] = None,
) -> list:
    resolver_calls: list = []

    def fake_get_budgets(db_session: object, user_id=None):
        return [budget]

    def fake_get_expenses(db_session: object, user_id=None):
        return expenses

    def fake_get_categories(db_session: object, user_id=None):
        return categories or []

    def fake_resolve_version_for_period(
        db_session: object,
        budget_id,
        period_start: date,
        period_end: date,
    ):
        resolver_calls.append((budget_id, period_start, period_end))
        return version

    monkeypatch.setattr(
        analytics_service.budgets_repository,
        "get_budgets",
        fake_get_budgets,
    )
    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_categories,
    )
    monkeypatch.setattr(
        analytics_service.budget_version_repository,
        "resolve_version_for_period",
        fake_resolve_version_for_period,
    )

    return resolver_calls


# Tests that an active monthly budget only counts expenses within the
# current calendar month, computes remaining/exceeded correctly, and
# reports the resolved period fields.
# This test exists to verify the core monthly calendar-period defect fix.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the September expense counts.
def test_get_budget_status_monthly_current_period(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("40.00"), date(2026, 9, 10)),
        make_expense(Decimal("999.00"), date(2026, 8, 31)),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period == "monthly"
    assert status.period_start == date(2026, 9, 1)
    assert status.period_end == date(2026, 9, 30)
    assert status.spent == Decimal("40.00")
    assert status.remaining == Decimal("60.00")
    assert status.period_state == "active"


# Tests that an active weekly budget only counts expenses within the
# current Monday-Sunday window.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the in-window expense counts.
def test_get_budget_status_weekly_current_period(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="weekly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("50.00"))
    expenses = [
        make_expense(Decimal("10.00"), date(2026, 9, 14)),  # Monday, in window
        make_expense(Decimal("999.00"), date(2026, 9, 7)),  # prior week
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - as_of is Wednesday 2026-09-16, week is Mon 09-14 to Sun 09-20
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period_start == date(2026, 9, 14)
    assert status.period_end == date(2026, 9, 20)
    assert status.spent == Decimal("10.00")


# Tests that an active yearly budget only counts expenses within the
# current calendar year, and that Dec 31/Jan 1 sit on opposite sides of
# the year boundary.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the current-year expense counts.
def test_get_budget_status_yearly_current_period_and_year_boundary(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="yearly", start_date=date(2020, 1, 1))
    version = make_version(limit_amount=Decimal("1000.00"))
    expenses = [
        make_expense(Decimal("30.00"), date(2026, 12, 31)),
        make_expense(Decimal("999.00"), date(2025, 12, 31)),  # prior year
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 12, 31),
    )[0]

    # Assert
    assert status.period_start == date(2026, 1, 1)
    assert status.period_end == date(2026, 12, 31)
    assert status.spent == Decimal("30.00")


# Tests that an expense on the last day of a month counts and one on the
# first day of the next month does not.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the in-month expense counts.
def test_get_budget_status_month_boundary(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("20.00"), date(2026, 9, 30)),
        make_expense(Decimal("999.00"), date(2026, 10, 1)),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - as_of is the last day of the month itself, so the Oct 1 expense
    # would be future-dated too; using as_of=2026-09-30 isolates the
    # month-boundary behavior from the future-dated-expense behavior.
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 30),
    )[0]

    # Assert
    assert status.spent == Decimal("20.00")


# Tests that a budget activated mid-month only counts expenses from its
# start_date onward, excluding earlier same-month spending, and flags the
# period as partial.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the pre-activation expense is excluded.
def test_get_budget_status_partial_first_period(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 9, 15))
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("999.00"), date(2026, 9, 10)),  # before activation
        make_expense(Decimal("30.00"), date(2026, 9, 15)),  # exact start_date
        make_expense(Decimal("20.00"), date(2026, 9, 18)),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 20),
    )[0]

    # Assert
    assert status.effective_start == date(2026, 9, 15)
    assert status.is_partial_period is True
    assert status.spent == Decimal("50.00")


# Tests that an ended budget reports status for its final effective period
# only - not its entire historical lifetime - and that an expense exactly
# on end_date still counts while one after it does not.
# This test exists to verify Section 5's "ended" lifecycle rule directly:
# summing all lifetime spending here would be wrong.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the final-period expenses count.
def test_get_budget_status_ended_budget_uses_final_period_not_lifetime(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(
        period="monthly",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 10),
    )
    version = make_version(limit_amount=Decimal("500.00"))
    expenses = [
        make_expense(Decimal("100.00"), date(2026, 1, 15)),  # earlier lifetime
        make_expense(Decimal("100.00"), date(2026, 2, 15)),  # earlier lifetime
        make_expense(Decimal("40.00"), date(2026, 3, 10)),  # exact end_date
        make_expense(Decimal("999.00"), date(2026, 3, 11)),  # after end_date
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - as_of is long after end_date
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period_state == "ended"
    assert status.period_start == date(2026, 3, 1)
    assert status.effective_end == date(2026, 3, 10)
    assert status.is_partial_period is True
    assert status.spent == Decimal("40.00")


# Tests that a budget not yet activated reports zero spend regardless of
# any expenses that exist, per Section 5's explicit not_started override.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if spent/remaining/exceeded reflect the override.
def test_get_budget_status_not_started_budget(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 12, 1))
    version = make_version(limit_amount=Decimal("300.00"))
    expenses = [
        make_expense(Decimal("999.00"), date(2026, 9, 16)),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period_state == "not_started"
    assert status.spent == Decimal("0")
    assert status.remaining == Decimal("300.00")
    assert status.exceeded_amount == Decimal("0")
    assert status.is_exceeded is False


# Tests that a future-dated expense within the current calendar period does
# not count toward today's status.
# This test exists to lock in the explicit Section 3 example: a Sept 25
# expense must not count when as_of is Sept 16, even though both fall in
# the September period.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the future-dated expense is excluded.
def test_get_budget_status_future_dated_expense_excluded(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("999.00"), date(2026, 9, 25)),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.spent == Decimal("0")


# Tests that an expense after effective_end (a budget deactivating mid
# period, still active as of today) is excluded even though it is before
# the calendar period_end.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the post-effective_end expense is excluded.
def test_get_budget_status_expense_after_effective_end_excluded(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(
        period="monthly",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 9, 20),
    )
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("15.00"), date(2026, 9, 20)),  # exact effective_end
        make_expense(Decimal("999.00"), date(2026, 9, 21)),  # after effective_end
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - as_of is exactly effective_end, still active (ended requires
    # as_of strictly greater than end_date); isolates the effective_end
    # boundary from the separate future-dated-expense cutoff.
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 20),
    )[0]

    # Assert
    assert status.period_state == "active"
    assert status.effective_end == date(2026, 9, 20)
    assert status.spent == Decimal("15.00")


# Tests that the resolved BudgetVersion, not the live budget's own values,
# supplies limit_amount and category_id in the response.
# This test exists because Section 2 explicitly forbids treating the
# current Budget row as historical truth once a version exists.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the response reflects the version, not budget.
def test_get_budget_status_uses_resolved_version_not_live_budget(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    version_category_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(
        limit_amount=Decimal("777.00"),
        category_id=version_category_id,
    )
    wire_budget_status_deps(monkeypatch, budget, [], version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.limit_amount == Decimal("777.00")
    assert status.category_id == version_category_id


# Tests that the service resolves the version using the budget's calendar
# period bounds (period_start/period_end), which is what lets the B2
# resolver pick the correct historical version for the requested period
# rather than always returning the latest one.
# This test exists to verify the service-to-resolver wiring, not the
# resolver's own disambiguation logic (already covered by B2's tests).
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the resolver was called with the current
#   calendar period's bounds.
def test_get_budget_status_resolves_version_for_current_period_bounds(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version()
    resolver_calls = wire_budget_status_deps(monkeypatch, budget, [], version)

    # Act
    analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )

    # Assert
    assert resolver_calls == [(budget.id, date(2026, 9, 1), date(2026, 9, 30))]


# Tests that a category-scoped budget only counts expenses in that
# category, and an unscoped budget (category_id None on the resolved
# version) counts all eligible expenses.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if scoping matches the resolved version's
#   category_id in both cases.
def test_get_budget_status_category_scoped_and_unscoped(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    transport_category_id = uuid4()

    scoped_budget = make_budget(id=uuid4(), period="monthly", start_date=date(2026, 1, 1))
    scoped_version = make_version(limit_amount=Decimal("100.00"), category_id=food_category_id)
    expenses = [
        make_expense(Decimal("30.00"), date(2026, 9, 10), category_id=food_category_id),
        make_expense(Decimal("20.00"), date(2026, 9, 10), category_id=transport_category_id),
    ]
    wire_budget_status_deps(monkeypatch, scoped_budget, expenses, scoped_version)

    scoped_status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    unscoped_budget = make_budget(id=uuid4(), period="monthly", start_date=date(2026, 1, 1))
    unscoped_version = make_version(limit_amount=Decimal("100.00"), category_id=None)
    wire_budget_status_deps(monkeypatch, unscoped_budget, expenses, unscoped_version)

    unscoped_status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert scoped_status.spent == Decimal("30.00")
    assert unscoped_status.spent == Decimal("50.00")


# Tests that two independently defined budgets scoping the same category
# each count the same expense in full, with no cross-budget deduplication.
# This test exists to preserve the explicit product rule that overlapping
# budgets are allowed and independent.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if both budgets report the full expense amount.
def test_get_budget_status_overlapping_budgets_remain_independent(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    category_id = uuid4()

    budget_a = make_budget(id=uuid4(), name="Budget A", period="monthly", start_date=date(2026, 1, 1))
    budget_b = make_budget(id=uuid4(), name="Budget B", period="monthly", start_date=date(2026, 1, 1))
    version_a = make_version(limit_amount=Decimal("100.00"), category_id=category_id)
    version_b = make_version(limit_amount=Decimal("200.00"), category_id=category_id)
    expenses = [make_expense(Decimal("30.00"), date(2026, 9, 10), category_id=category_id)]

    versions_by_budget = {budget_a.id: version_a, budget_b.id: version_b}

    def fake_get_budgets(db_session: object, user_id=None):
        return [budget_a, budget_b]

    def fake_get_expenses(db_session: object, user_id=None):
        return expenses

    def fake_get_categories(db_session: object, user_id=None):
        return []

    def fake_resolve_version_for_period(db_session, budget_id, period_start, period_end):
        return versions_by_budget[budget_id]

    monkeypatch.setattr(analytics_service.budgets_repository, "get_budgets", fake_get_budgets)
    monkeypatch.setattr(analytics_service.expenses_repository, "get_expenses", fake_get_expenses)
    monkeypatch.setattr(analytics_service.categories_repository, "get_categories", fake_get_categories)
    monkeypatch.setattr(
        analytics_service.budget_version_repository,
        "resolve_version_for_period",
        fake_resolve_version_for_period,
    )

    # Act
    statuses = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )

    # Assert
    assert statuses[0].spent == Decimal("30.00")
    assert statuses[1].spent == Decimal("30.00")


# Tests utilization_percent below, exactly at, and above 100, and that it
# is never clamped down when a budget is exceeded.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if utilization/exceeded/remaining match for all
#   three cases.
def test_get_budget_status_utilization_below_at_and_above_100(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()

    cases = [
        (Decimal("50.00"), Decimal("50.00"), Decimal("0.00"), False),
        (Decimal("100.00"), Decimal("0.00"), Decimal("0.00"), False),
        (Decimal("150.00"), Decimal("0.00"), Decimal("50.00"), True),
    ]

    for spent_amount, expected_remaining, expected_exceeded, expected_is_exceeded in cases:
        budget = make_budget(id=uuid4(), period="monthly", start_date=date(2026, 1, 1))
        version = make_version(limit_amount=Decimal("100.00"))
        expenses = [make_expense(spent_amount, date(2026, 9, 10))]
        wire_budget_status_deps(monkeypatch, budget, expenses, version)

        # Act
        status = analytics_service.get_budget_status(
            db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
        )[0]

        # Assert
        assert status.remaining == expected_remaining
        assert status.exceeded_amount == expected_exceeded
        assert status.is_exceeded is expected_is_exceeded
        assert status.utilization_percent == (
            spent_amount / Decimal("100.00") * Decimal("100")
        ).quantize(Decimal("0.01"))


# Tests that spent is computed as an exact Decimal sum with no floating
# point drift, using values that fail under float arithmetic.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the sum is exactly Decimal("0.30").
def test_get_budget_status_decimal_precision(monkeypatch: MonkeyPatch) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("10.00"))
    expenses = [make_expense(Decimal("0.10"), date(2026, 9, i)) for i in (10, 11, 12)]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.spent == Decimal("0.30")
    assert isinstance(status.spent, Decimal)


# Tests that an expense in a different currency than the budget is never
# summed into spent, even though it would otherwise match category/period.
# This test exists to lock in Section 8: no fake conversion, no silent
# numeric mixing of currencies.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only the same-currency expense counts.
def test_get_budget_status_currency_mismatch_never_summed(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1), currency="EUR")
    version = make_version(limit_amount=Decimal("100.00"))
    expenses = [
        make_expense(Decimal("20.00"), date(2026, 9, 10), currency="EUR"),
        make_expense(Decimal("999.00"), date(2026, 9, 10), currency="USD"),
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.spent == Decimal("20.00")


# ---------------------------------------------------------------------------
# get_budget_status - VF-014B4 smart metrics orchestration
#
# Formula correctness itself is covered exhaustively in
# tests/unit/budgets/test_budget_metrics.py against the pure function
# directly. These tests verify the wiring: that get_budget_status feeds
# budget_metrics.calculate_budget_metrics the correctly B1/B2/B3-resolved
# inputs (window days, resolved version limit, filtered spent), not that
# the arithmetic itself is right.
# ---------------------------------------------------------------------------


# Tests that B1's resolved window day counts (days_in_period/days_elapsed)
# feed directly into the response's B4 day fields for an active budget.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the response's day fields match the window
#   B1 resolved for this as_of.
def test_get_budget_status_metrics_use_b1_resolved_window_days(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("600.00"))
    expenses = [make_expense(Decimal("320.00"), date(2026, 9, 16))]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - September has 30 days, as_of is the 16th
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.days_in_period == 30
    assert status.days_elapsed == 16
    assert status.days_remaining == 15  # 30 - 16 + 1, today counted in both


# Tests that the resolved BudgetVersion's limit_amount, not the live
# budget's own value, drives the B4 metrics (allowance/projection/risk).
# This test exists because Section 2 of VF-014B2/B3 already forbids
# treating the live budget as historical truth - B4's metrics must inherit
# that same discipline rather than reading the budget directly.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if allowance/projection reflect the version's
#   limit even though the budget SimpleNamespace has no limit_amount at all.
def test_get_budget_status_metrics_use_resolved_version_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1))
    version = make_version(limit_amount=Decimal("300.00"))
    expenses = [make_expense(Decimal("100.00"), date(2026, 9, 10))]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act - as_of the 10th, 10 elapsed days
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 10),
    )[0]

    # Assert
    assert status.limit_amount == Decimal("300.00")
    # projected = (100/10)*30 = 300.00 -> exactly the version's limit
    assert status.projected_spending == Decimal("300.00")
    assert status.risk_status == "watch"


# Tests that the same currency/category/period-filtered spent value B3
# already computes is exactly what feeds average_daily_spending and the
# projection - not an unfiltered total.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the excluded expenses (wrong category, future-
#   dated, wrong currency) do not influence average_daily_spending.
def test_get_budget_status_metrics_use_filtered_spent(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    food_category_id = uuid4()
    other_category_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1), currency="EUR")
    version = make_version(limit_amount=Decimal("100.00"), category_id=food_category_id)
    expenses = [
        make_expense(Decimal("20.00"), date(2026, 9, 10), category_id=food_category_id),  # counts
        make_expense(Decimal("999.00"), date(2026, 9, 10), category_id=other_category_id),  # wrong category
        make_expense(Decimal("999.00"), date(2026, 9, 25), category_id=food_category_id),  # future
        make_expense(Decimal("999.00"), date(2026, 9, 10), category_id=food_category_id, currency="USD"),  # wrong currency
    ]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 10),
    )[0]

    # Assert
    assert status.spent == Decimal("20.00")
    assert status.average_daily_spending == Decimal("2.00")  # 20.00 / 10 elapsed days


# Tests that a partial-period budget's effective day count (not the full
# calendar month) feeds the B4 metrics.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if days_in_period/projection use the 15-day
#   partial window, matching the task's own worked example.
def test_get_budget_status_metrics_partial_period_uses_effective_days(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange - activated Sept 16, effective window Sept 16-30 = 15 days
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 9, 16))
    version = make_version(limit_amount=Decimal("300.00"))
    expenses = [make_expense(Decimal("50.00"), date(2026, 9, 18))]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 20),
    )[0]

    # Assert
    assert status.days_in_period == 15
    assert status.days_elapsed == 5
    assert status.days_remaining == 11
    assert status.projected_spending == Decimal("150.00")  # (50/5)*15


# Tests that a not_started budget's B4 fields flow correctly through the
# full service call, not only the pure metrics function in isolation.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the response matches the not_started rules.
def test_get_budget_status_metrics_not_started_via_service(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 12, 1))
    version = make_version(limit_amount=Decimal("300.00"))
    wire_budget_status_deps(monkeypatch, budget, [], version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period_state == "not_started"
    assert status.days_elapsed == 0
    assert status.projected_spending is None
    assert status.projected_surplus is None
    assert status.projected_deficit is None
    assert status.risk_status == "healthy"


# Tests that an ended budget's B4 fields flow correctly through the full
# service call.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the response matches the ended rules and
#   uses the final period's spend, not lifetime spend.
def test_get_budget_status_metrics_ended_via_service(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    budget = make_budget(period="monthly", start_date=date(2026, 1, 1), end_date=date(2026, 3, 10))
    version = make_version(limit_amount=Decimal("500.00"))
    expenses = [make_expense(Decimal("40.00"), date(2026, 3, 10))]
    wire_budget_status_deps(monkeypatch, budget, expenses, version)

    # Act
    status = analytics_service.get_budget_status(
        db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
    )[0]

    # Assert
    assert status.period_state == "ended"
    assert status.days_remaining == 0
    assert status.daily_spending_allowance == Decimal("0.00")
    assert status.projected_spending == Decimal("40.00")
    assert status.risk_status == "healthy"


# Tests that goal progress calculates remaining amount and progress percentage.
# This test exists to verify financial goal analytics business logic without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if goal progress values are calculated correctly.
def test_get_goal_progress_calculates_remaining_amount_and_progress_percent(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    goal_id = uuid4()

    goals = [
        make_model(
            id=goal_id,
            name="Vacation",
            target_amount=Decimal("2000.00"),
            current_amount=Decimal("500.00"),
            status="active",
            target_date=date(2026, 12, 31),
        ),
    ]

    def fake_get_goals(db_session: object, user_id=None):
        return goals

    monkeypatch.setattr(
        analytics_service.goals_repository,
        "get_goals",
        fake_get_goals,
    )

    # Act
    goal_progress = analytics_service.get_goal_progress(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    vacation_goal = goal_progress[0]

    assert vacation_goal.goal_id == goal_id
    assert vacation_goal.name == "Vacation"
    assert vacation_goal.target_amount == Decimal("2000.00")
    assert vacation_goal.current_amount == Decimal("500.00")
    assert vacation_goal.remaining_amount == Decimal("1500.00")
    assert vacation_goal.progress_percent == Decimal("25.00")
    assert vacation_goal.status == "active"
    assert vacation_goal.target_date == date(2026, 12, 31)


# Tests that analytics service returns empty values when repositories return no data.
# This test exists to verify empty dashboard state without API or database.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if empty analytics responses are safe and predictable.
def test_analytics_service_returns_empty_results_when_no_data_exists(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, object())
    user_id = uuid4()
    wire_base_currency(monkeypatch, "EUR")

    def fake_get_empty_items(db_session: object, user_id=None):
        return []

    monkeypatch.setattr(
        analytics_service.expenses_repository,
        "get_expenses",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.budgets_repository,
        "get_budgets",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.categories_repository,
        "get_categories",
        fake_get_empty_items,
    )
    monkeypatch.setattr(
        analytics_service.goals_repository,
        "get_goals",
        fake_get_empty_items,
    )

    # Act
    monthly_summary = analytics_service.get_monthly_summary(
        db_session=db_session,
        user_id=user_id,
        year=2026,
        month=5,
    )
    category_summary = analytics_service.get_category_summary(
        db_session=db_session,
        user_id=user_id,
    )
    budget_status = analytics_service.get_budget_status(
        db_session=db_session,
        user_id=user_id,
        as_of=date(2026, 5, 15),
    )
    goal_progress = analytics_service.get_goal_progress(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    assert monthly_summary.total_spent == Decimal("0")
    assert monthly_summary.expenses_count == 0
    assert monthly_summary.unresolved_expenses_count == 0
    assert monthly_summary.base_currency == "EUR"
    assert category_summary == []
    assert budget_status == []
    assert goal_progress == []


# Tests that editing a budget's limit today uses the new BudgetVersion for
# the current period, while a query for a past period still resolves the
# original configuration - the edit must never leak backward.
# This test exists to verify VF-014B3 requirement H (historical previous-
# period configuration is not accidentally used) against a real database
# and the real budget_service, since the public API no longer exposes an
# arbitrary as_of and can only ever report the current period - this
# scenario is only reachable at the service layer now, which is exactly
# why get_budget_status keeps as_of as an explicit, internal parameter.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the current-period query reflects the new
#   limit and the past-period query still reflects the original one.
def test_get_budget_status_edit_uses_current_version_past_period_unaffected(
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
                start_date=date(2026, 1, 1),
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

        # Act
        current_status = analytics_service.get_budget_status(
            db_session=db_session, user_id=user_id, as_of=date(2026, 9, 16),
        )[0]
        past_status = analytics_service.get_budget_status(
            db_session=db_session, user_id=user_id, as_of=date(2026, 3, 15),
        )[0]

        # Assert
        assert current_status.limit_amount == Decimal("600.00")
        assert past_status.limit_amount == Decimal("500.00")
    finally:
        db_session.close()