from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional, cast
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import account_service, account_transfer_service
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate
from app.modules.accounts.account_transfer_schemas import AccountTransferCreate
from app.modules.analytics import analytics_service
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate
from app.modules.fx import fx_ecb_provider, fx_nbu_provider, fx_service
from app.modules.fx.fx_schemas import FxRateResult
from app.modules.goals import goal_service
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate
from app.modules.income import income_service
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate

# VF-019B Financial Overview service tests. Every call passes an explicit
# as_of - nothing here depends on the wall clock (VF-CI-02 lesson).
#
# The first part replaces the two date-range repository reads with fakes
# that apply the same inclusive date filter the database does, so the
# date semantics, money arithmetic, and FX inclusion rules are exercised
# precisely. The second part runs against the real test database with the
# real Account/Transfer/Goal/Income/Expense services, to prove that
# non-canonical operations cannot influence the overview.

AS_OF = date(2026, 10, 2)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


# Creates a fake Income record carrying only the fields the overview reads.
# Parameters:
# - received_at: the Income's financial date.
# - base_amount: resolved base-currency amount as a string, or None for an
#   unresolved record.
# - base_currency: snapshot base currency; defaults to EUR when resolved.
# Returns:
# - SimpleNamespace imitating an IncomeModel.
def _income(received_at: date, base_amount: Optional[str], base_currency: Optional[str] = "EUR"):
    return SimpleNamespace(
        received_at=received_at,
        base_amount=Decimal(base_amount) if base_amount is not None else None,
        base_currency=base_currency if base_amount is not None else None,
    )


# Creates a fake Expense record carrying only the fields the overview reads.
# Parameters: same as _income, with expense_date as the financial date.
# Returns:
# - SimpleNamespace imitating an ExpenseModel.
def _expense(expense_date: date, base_amount: Optional[str], base_currency: Optional[str] = "EUR"):
    return SimpleNamespace(
        expense_date=expense_date,
        base_amount=Decimal(base_amount) if base_amount is not None else None,
        base_currency=base_currency if base_amount is not None else None,
    )


# Replaces the base-currency lookup and both date-range reads with fakes.
# The fakes filter by the inclusive [start_date, end_date] window exactly
# like the real queries and record every call, so tests can assert both
# the result and the bounds the service asked for.
# Parameters:
# - monkeypatch: pytest fixture used to replace the dependencies.
# - income: fake Income records of the user.
# - expenses: fake Expense records of the user.
# - base_currency: the user's base currency.
# Returns:
# - Dictionary with the recorded (user_id, start_date, end_date) calls
#   under "income" and "expenses".
def _wire(monkeypatch: MonkeyPatch, income=(), expenses=(), base_currency: str = "EUR") -> dict:
    calls: dict = {"income": [], "expenses": []}

    def fake_income(db_session, user_id, start_date, end_date):
        calls["income"].append((user_id, start_date, end_date))
        return [record for record in income if start_date <= record.received_at <= end_date]

    def fake_expenses(db_session, user_id, start_date, end_date):
        calls["expenses"].append((user_id, start_date, end_date))
        return [record for record in expenses if start_date <= record.expense_date <= end_date]

    monkeypatch.setattr(
        analytics_service.financial_settings_service,
        "get_base_currency",
        lambda db_session, user_id: base_currency,
    )
    monkeypatch.setattr(analytics_service.income_repository, "get_income_in_date_range", fake_income)
    monkeypatch.setattr(analytics_service.expenses_repository, "get_expenses_in_date_range", fake_expenses)

    return calls


def _overview(year: int, month: int, as_of: date = AS_OF, user_id=None):
    return analytics_service.get_financial_overview(
        db_session=cast(Session, object()),
        user_id=user_id or uuid4(),
        year=year,
        month=month,
        as_of=as_of,
    )


def _trend(count: int, as_of: date = AS_OF):
    return analytics_service.get_income_expense_trend(
        db_session=cast(Session, object()),
        user_id=uuid4(),
        count=count,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# A. Money: totals, Net (Income - Expenses), savings rate
# ---------------------------------------------------------------------------


# Tests a month with Income only: Net equals income and the savings rate is
# exactly 100.00.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if totals and the rate match.
def test_overview_income_only(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch, income=[_income(date(2026, 9, 10), "2500.00")])

    overview = _overview(2026, 9)

    assert overview.income_total == Decimal("2500.00")
    assert overview.expense_total == Decimal("0.00")
    assert overview.net_flow == Decimal("2500.00")
    assert overview.savings_rate_percent == Decimal("100.00")
    assert overview.income_count == 1
    assert overview.expense_count == 0


# Tests a month with Expenses only: zero income gives a negative Net and a
# null savings rate - never a division by zero or a fabricated value.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the rate is None and Net is negative.
def test_overview_expenses_only_has_null_savings_rate(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch, expenses=[_expense(date(2026, 9, 3), "120.50")])

    overview = _overview(2026, 9)

    assert overview.income_total == Decimal("0.00")
    assert overview.expense_total == Decimal("120.50")
    assert overview.net_flow == Decimal("-120.50")
    assert overview.savings_rate_percent is None


# Tests positive, zero, and negative Net with their exact savings rates,
# including a fractional rate and an unclamped negative rate.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if every case matches its precomputed value.
def test_overview_net_and_savings_rate_cases(monkeypatch: MonkeyPatch) -> None:
    cases = [
        # (income, expense, net, rate)
        ("3000.00", "1830.40", "1169.60", "38.99"),
        ("1000.00", "1000.00", "0.00", "0.00"),
        ("1000.00", "1250.50", "-250.50", "-25.05"),
        ("3.00", "2.00", "1.00", "33.33"),
    ]

    for income_amount, expense_amount, net, rate in cases:
        _wire(
            monkeypatch,
            income=[_income(date(2026, 9, 1), income_amount)],
            expenses=[_expense(date(2026, 9, 2), expense_amount)],
        )

        overview = _overview(2026, 9)

        assert overview.net_flow == Decimal(net), (income_amount, expense_amount)
        assert overview.savings_rate_percent == Decimal(rate), (income_amount, expense_amount)


# Tests the explicit rounding rule: an exact half-cent rate rounds to the
# even neighbour (ROUND_HALF_EVEN) - 12.345 -> 12.34, where ROUND_HALF_UP
# would give 12.35 - for positive and negative rates alike.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if both ties round half-even.
def test_overview_savings_rate_rounds_half_even(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "200.00")],
        expenses=[_expense(date(2026, 9, 2), "175.31")],
    )
    assert _overview(2026, 9).savings_rate_percent == Decimal("12.34")

    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "200.00")],
        expenses=[_expense(date(2026, 9, 2), "224.69")],
    )
    assert _overview(2026, 9).savings_rate_percent == Decimal("-12.34")


# Tests the zero-sign normalization of the savings rate: a tiny negative
# rate that rounds to zero is a plain 0.00 (never "-0.00"), while Net keeps
# its real negative value; a negative rate that rounds to a non-zero value
# stays negative; and zero income still yields None.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if all three cases match.
def test_overview_savings_rate_never_negative_zero(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "1000000.00")],
        expenses=[_expense(date(2026, 9, 2), "1000000.01")],
    )
    rounds_to_zero = _overview(2026, 9)

    assert rounds_to_zero.net_flow == Decimal("-0.01")
    assert str(rounds_to_zero.net_flow) == "-0.01"
    assert rounds_to_zero.savings_rate_percent == Decimal("0.00")
    assert str(rounds_to_zero.savings_rate_percent) == "0.00"
    assert rounds_to_zero.savings_rate_percent.is_signed() is False

    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "1000.00")],
        expenses=[_expense(date(2026, 9, 2), "1000.10")],
    )
    small_negative = _overview(2026, 9)

    assert small_negative.net_flow == Decimal("-0.10")
    assert str(small_negative.savings_rate_percent) == "-0.01"

    _wire(monkeypatch, expenses=[_expense(date(2026, 9, 2), "0.01")])
    zero_income = _overview(2026, 9)

    assert zero_income.net_flow == Decimal("-0.01")
    assert zero_income.savings_rate_percent is None


# Tests Decimal exactness and two-place representation: many cent amounts
# sum exactly (no float drift) and the totals keep two decimal places.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the sums are exact and two-place.
def test_overview_sums_are_exact_decimals(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "0.10") for _ in range(10)],
        expenses=[_expense(date(2026, 9, 2), "0.10"), _expense(date(2026, 9, 3), "0.20")],
    )

    overview = _overview(2026, 9)

    assert overview.income_total == Decimal("1.00")
    assert overview.expense_total == Decimal("0.30")
    assert overview.net_flow == Decimal("0.70")
    assert str(overview.income_total) == "1.00"
    assert str(overview.net_flow) == "0.70"
    assert overview.savings_rate_percent == Decimal("70.00")


# Tests the empty month: all money is 0.00 (two places), counts are zero,
# the rate is null, and data is complete.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the safe empty state is returned.
def test_overview_empty_month(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch)

    overview = _overview(2026, 9)

    assert str(overview.income_total) == "0.00"
    assert str(overview.expense_total) == "0.00"
    assert str(overview.net_flow) == "0.00"
    assert overview.savings_rate_percent is None
    assert (overview.income_count, overview.expense_count) == (0, 0)
    assert (overview.unresolved_income_count, overview.unresolved_expense_count) == (0, 0)
    assert overview.data_status == "complete_data"
    assert overview.base_currency == "EUR"


# ---------------------------------------------------------------------------
# C. FX: resolved / unresolved inclusion
# ---------------------------------------------------------------------------


# Tests that unresolved records (base_amount NULL, or a snapshot in another
# base currency) are excluded from the sums, counted separately per side,
# and make the data incomplete - while resolved records still count.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if sums, counts, and data_status match.
def test_overview_unresolved_records_are_excluded_and_counted(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[
            _income(date(2026, 9, 1), "1000.00"),
            _income(date(2026, 9, 2), None),
            _income(date(2026, 9, 3), "500.00", base_currency="USD"),
        ],
        expenses=[
            _expense(date(2026, 9, 4), "200.00"),
            _expense(date(2026, 9, 5), None),
        ],
    )

    overview = _overview(2026, 9)

    assert overview.income_total == Decimal("1000.00")
    assert overview.expense_total == Decimal("200.00")
    assert overview.income_count == 1
    assert overview.unresolved_income_count == 2
    assert overview.expense_count == 1
    assert overview.unresolved_expense_count == 1
    assert overview.net_flow == Decimal("800.00")
    assert overview.savings_rate_percent == Decimal("80.00")
    assert overview.data_status == "incomplete_data"


# Tests that a month whose only Income is unresolved reports income 0.00
# with a null rate - flagged incomplete, never silently a known zero.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the rate is null and data is incomplete.
def test_overview_only_unresolved_income_is_incomplete_not_zero(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch, income=[_income(date(2026, 9, 1), None)])

    overview = _overview(2026, 9)

    assert overview.income_total == Decimal("0.00")
    assert overview.unresolved_income_count == 1
    assert overview.savings_rate_percent is None
    assert overview.data_status == "incomplete_data"


# Tests that unresolved records outside the period do not make the period
# incomplete.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if data_status stays complete.
def test_overview_unresolved_outside_period_does_not_count(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[_income(date(2026, 8, 31), None)],
        expenses=[_expense(date(2026, 10, 1), None), _expense(date(2026, 9, 9), "10.00")],
    )

    overview = _overview(2026, 9)

    assert overview.unresolved_income_count == 0
    assert overview.unresolved_expense_count == 0
    assert overview.data_status == "complete_data"


# ---------------------------------------------------------------------------
# D. Time: period states and boundaries
# ---------------------------------------------------------------------------


# Tests a complete historical month: the whole month is queried and
# included, and the state is "complete".
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if bounds, state, and totals match.
def test_overview_complete_month_includes_whole_month(monkeypatch: MonkeyPatch) -> None:
    user_id = uuid4()
    calls = _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "10.00"), _income(date(2026, 9, 30), "20.00")],
        expenses=[_expense(date(2026, 8, 31), "99.00"), _expense(date(2026, 10, 1), "99.00")],
    )

    overview = _overview(2026, 9, user_id=user_id)

    assert overview.period_state == "complete"
    assert (overview.period_start, overview.period_end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert overview.effective_end == date(2026, 9, 30)
    assert overview.as_of == AS_OF
    assert overview.income_total == Decimal("30.00")
    assert overview.expense_total == Decimal("0.00")
    assert calls["income"] == [(user_id, date(2026, 9, 1), date(2026, 9, 30))]
    assert calls["expenses"] == [(user_id, date(2026, 9, 1), date(2026, 9, 30))]


# Tests the month in progress: records through as_of are included, records
# dated tomorrow (future-dated) are not, and effective_end is as_of.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if only records up to as_of count.
def test_overview_current_month_excludes_records_after_today(monkeypatch: MonkeyPatch) -> None:
    calls = _wire(
        monkeypatch,
        income=[_income(date(2026, 10, 1), "1000.00"), _income(date(2026, 10, 3), "5000.00")],
        expenses=[_expense(date(2026, 10, 2), "300.00"), _expense(date(2026, 10, 31), "700.00")],
    )

    overview = _overview(2026, 10)

    assert overview.period_state == "in_progress"
    assert overview.effective_end == AS_OF
    assert overview.income_total == Decimal("1000.00")
    assert overview.expense_total == Decimal("300.00")
    assert overview.savings_rate_percent == Decimal("70.00")
    assert calls["income"][0][1:] == (date(2026, 10, 1), AS_OF)


# Tests the last calendar day: the month is still "in_progress" with
# effective_end == period_end, and it becomes "complete" on the first day
# of the next month.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the state flips only on the next day.
def test_overview_last_day_is_in_progress_until_next_day(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch, income=[_income(date(2026, 9, 30), "10.00")])

    on_last_day = _overview(2026, 9, as_of=date(2026, 9, 30))
    next_day = _overview(2026, 9, as_of=date(2026, 10, 1))

    assert on_last_day.period_state == "in_progress"
    assert on_last_day.effective_end == date(2026, 9, 30)
    assert on_last_day.income_total == Decimal("10.00")
    assert next_day.period_state == "complete"
    assert next_day.effective_end == date(2026, 9, 30)
    assert next_day.income_total == Decimal("10.00")


# Tests a future month: valid (no error), all zeros, null rate and
# effective_end, complete data, and no repository read at all.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the future state is returned without reads.
def test_overview_future_month_is_zero_without_reads(monkeypatch: MonkeyPatch) -> None:
    calls = _wire(
        monkeypatch,
        income=[_income(date(2026, 11, 5), "5000.00")],
        expenses=[_expense(date(2026, 11, 6), "10.00")],
    )

    overview = _overview(2026, 11)

    assert overview.period_state == "future"
    assert overview.effective_end is None
    assert (overview.period_start, overview.period_end) == (date(2026, 11, 1), date(2026, 11, 30))
    assert overview.income_total == Decimal("0.00")
    assert overview.expense_total == Decimal("0.00")
    assert overview.net_flow == Decimal("0.00")
    assert overview.savings_rate_percent is None
    assert overview.data_status == "complete_data"
    assert calls == {"income": [], "expenses": []}


# Tests calendar boundaries: December viewed from January is complete with
# the right bounds, and February's end follows leap years.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if every month resolves the right bounds.
def test_overview_year_end_and_february_bounds(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch)

    december = _overview(2026, 12, as_of=date(2027, 1, 1))
    leap_february = _overview(2028, 2, as_of=date(2028, 3, 1))
    february = _overview(2027, 2, as_of=date(2027, 3, 1))

    assert (december.period_start, december.period_end) == (date(2026, 12, 1), date(2026, 12, 31))
    assert december.period_state == "complete"
    assert leap_february.period_end == date(2028, 2, 29)
    assert february.period_end == date(2027, 2, 28)


# ---------------------------------------------------------------------------
# E. Trend
# ---------------------------------------------------------------------------


# Tests the trend window: `count` monthly buckets, oldest first, ending
# with the month containing as_of, including empty months, with one bounded
# read per side from the first bucket's start through as_of.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if buckets, ordering, and reads match.
def test_trend_buckets_are_chronological_and_bounded(monkeypatch: MonkeyPatch) -> None:
    calls = _wire(
        monkeypatch,
        income=[_income(date(2026, 7, 15), "100.00"), _income(date(2026, 10, 1), "40.00")],
        expenses=[_expense(date(2026, 9, 2), "30.00"), _expense(date(2026, 10, 9), "500.00")],
    )

    trend = _trend(4)

    starts = [bucket.period_start for bucket in trend.buckets]
    assert starts == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    assert trend.count == 4
    assert trend.as_of == AS_OF
    assert trend.base_currency == "EUR"

    july, august, september, october = trend.buckets
    assert july.income_total == Decimal("100.00") and july.is_complete is True
    assert august.income_total == Decimal("0.00") and august.expense_total == Decimal("0.00")
    assert august.savings_rate_percent is None
    assert september.expense_total == Decimal("30.00") and september.net_flow == Decimal("-30.00")
    # The current month includes records through as_of only: the
    # 2026-10-09 expense is future-dated and excluded.
    assert october.income_total == Decimal("40.00")
    assert october.expense_total == Decimal("0.00")
    assert october.effective_end == AS_OF
    assert october.is_complete is False
    assert [call[1:] for call in calls["income"]] == [(date(2026, 7, 1), AS_OF)]
    assert [call[1:] for call in calls["expenses"]] == [(date(2026, 7, 1), AS_OF)]


# Tests count=1 (only the current month) and count=24 (two full years,
# crossing year boundaries correctly).
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if both windows have the right size and bounds.
def test_trend_count_one_and_twenty_four(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch)

    single = _trend(1)
    full = _trend(24)

    assert [bucket.period_start for bucket in single.buckets] == [date(2026, 10, 1)]
    assert len(full.buckets) == 24
    assert full.buckets[0].period_start == date(2024, 11, 1)
    assert full.buckets[-1].period_start == date(2026, 10, 1)
    assert all(
        earlier.period_end < later.period_start
        for earlier, later in zip(full.buckets, full.buckets[1:])
    )


# Tests the December -> January crossing: the window walks back over the
# year end, and the bucket ending on the last day of the as_of month is
# not complete.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if the crossing buckets are right.
def test_trend_crosses_year_end(monkeypatch: MonkeyPatch) -> None:
    _wire(monkeypatch, expenses=[_expense(date(2026, 12, 31), "12.00")])

    trend = _trend(3, as_of=date(2027, 1, 31))

    assert [bucket.period_start for bucket in trend.buckets] == [
        date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1),
    ]
    assert trend.buckets[1].expense_total == Decimal("12.00")
    assert trend.buckets[1].is_complete is True
    assert trend.buckets[2].is_complete is False
    assert trend.buckets[2].effective_end == date(2027, 1, 31)


# Tests per-bucket resolved/unresolved counts in the trend.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if each bucket counts only its own records.
def test_trend_counts_resolved_and_unresolved_per_bucket(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[_income(date(2026, 9, 1), "10.00"), _income(date(2026, 9, 2), None)],
        expenses=[_expense(date(2026, 10, 1), None), _expense(date(2026, 10, 2), "5.00")],
    )

    september, october = _trend(2).buckets

    assert (september.income_count, september.unresolved_income_count) == (1, 1)
    assert (september.expense_count, september.unresolved_expense_count) == (0, 0)
    assert (october.expense_count, october.unresolved_expense_count) == (1, 1)
    assert october.expense_total == Decimal("5.00")


# Tests that every trend bucket carries exactly the figures the
# single-month overview returns for the same month and as_of.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository calls.
# Returns:
# - None. The test passes if overview and trend agree for every month.
def test_trend_buckets_match_single_month_overview(monkeypatch: MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        income=[
            _income(date(2026, 8, 1), "2000.00"),
            _income(date(2026, 9, 15), "333.33"),
            _income(date(2026, 9, 16), None),
            _income(date(2026, 10, 2), "100.00"),
            _income(date(2026, 10, 20), "900.00"),
        ],
        expenses=[
            _expense(date(2026, 8, 31), "1999.99"),
            _expense(date(2026, 9, 1), "400.00"),
            _expense(date(2026, 10, 1), "25.50"),
        ],
    )
    figure_fields = [
        "income_total", "expense_total", "net_flow", "savings_rate_percent",
        "income_count", "expense_count", "unresolved_income_count", "unresolved_expense_count",
    ]

    for bucket in _trend(3).buckets:
        overview = _overview(bucket.period_start.year, bucket.period_start.month)

        for field in figure_fields:
            assert getattr(bucket, field) == getattr(overview, field), (bucket.period_start, field)
        assert bucket.effective_end == overview.effective_end
        assert bucket.is_complete == (overview.period_state == "complete")


# ---------------------------------------------------------------------------
# B, C, F. Real database: canonical sources, FX snapshots, isolation
# ---------------------------------------------------------------------------


# Deterministic stand-in for fx_service.resolve_fx_rate used while creating
# foreign-currency records (VF-CI-01 pattern): identity for same-currency
# pairs, a fixed 0.9 rate otherwise.
def _deterministic_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
    if original_currency == base_currency:
        return FxRateResult(rate=Decimal("1"), actual_rate_date=transaction_date, source="identity")

    return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")


# Tests (B) that only canonical Income/Expense records reach the overview:
# an opening balance, credit/debit adjustments, a posted and a planned
# Transfer, and a Goal contribution/withdrawal - all dated inside the
# month and all present in their own ledgers - change nothing, Account-
# linked records are counted exactly once (their ledger projections are
# not read), unlinked records count equally, and a refund is income.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the five canonical records count.
def test_overview_counts_only_canonical_records_against_database(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        checking = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("5000.00"), opening_balance_date=date(2026, 9, 1),
            ),
            user_id=user_id,
        )
        savings = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Savings", type="savings", currency="EUR"),
            user_id=user_id,
        )
        for direction, amount in (("credit", "700.00"), ("debit", "40.00")):
            account_service.create_account_transaction(
                db_session=db_session,
                account_id=checking.id,
                transaction_data=AccountTransactionCreate(
                    direction=direction, amount=Decimal(amount), transaction_date=date(2026, 9, 5),
                ),
                user_id=user_id,
            )

        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("3000.00"), currency="EUR", received_at=date(2026, 9, 10),
                source="salary", account_id=checking.id,
            ),
            user_id=user_id,
        )
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("200.00"), currency="EUR", received_at=date(2026, 9, 12),
                source="freelance",
            ),
            user_id=user_id,
        )
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("49.90"), currency="EUR", received_at=date(2026, 9, 14),
                source="refund",
            ),
            user_id=user_id,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Rent", amount=Decimal("1200.00"), currency="EUR",
                expense_date=date(2026, 9, 3), account_id=checking.id,
            ),
            user_id=user_id,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Cash lunch", amount=Decimal("15.50"), currency="EUR",
                expense_date=date(2026, 9, 4),
            ),
            user_id=user_id,
        )

        posted = account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=AccountTransferCreate(
                client_request_id=uuid4(), source_account_id=checking.id,
                destination_account_id=savings.id, amount=Decimal("500.00"),
                transfer_date=date(2026, 9, 20),
            ),
            user_id=user_id,
            as_of=AS_OF,
        ).transfer
        planned = account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=AccountTransferCreate(
                client_request_id=uuid4(), source_account_id=savings.id,
                destination_account_id=checking.id, amount=Decimal("250.00"),
                transfer_date=date(2026, 9, 25),
            ),
            user_id=user_id,
            as_of=date(2026, 9, 1),
        ).transfer
        assert (posted.status, planned.status) == ("posted", "planned")

        goal = goal_service.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(name="Trip", target_amount=Decimal("1000.00"), currency="EUR"),
            user_id=user_id,
        )
        for kind, amount in (("contribution", "300.00"), ("withdrawal", "100.00")):
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal.id,
                transaction_data=GoalTransactionCreate(type=kind, amount=Decimal(amount)),
                user_id=user_id,
            )

        # The non-canonical operations really exist in the Account ledger,
        # so the totals below prove exclusion, not absence.
        ledger_kinds = {
            row.kind
            for row in db_session.query(AccountTransactionModel).filter(
                AccountTransactionModel.user_id == user_id,
            )
        }
        assert ledger_kinds == {"opening_balance", "adjustment", "income", "expense", "transfer"}

        overview = analytics_service.get_financial_overview(
            db_session=db_session, user_id=user_id, year=2026, month=9, as_of=AS_OF,
        )

        assert overview.income_total == Decimal("3249.90")
        assert overview.expense_total == Decimal("1215.50")
        assert overview.net_flow == Decimal("2034.40")
        assert overview.savings_rate_percent == Decimal("62.60")
        assert (overview.income_count, overview.expense_count) == (3, 2)
        assert overview.data_status == "complete_data"
    finally:
        db_session.close()


# Tests (C) foreign-currency records against the database: the overview
# sums the persisted historical base_amount snapshots, and the read path
# never resolves FX or calls a provider.
# Parameters:
# - monkeypatch: pytest fixture used to control FX resolution.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if snapshots are summed with no FX calls.
def test_overview_uses_persisted_fx_snapshots_without_fx_calls(
    monkeypatch: MonkeyPatch,
    clean_database: None,
) -> None:
    monkeypatch.setattr(fx_service, "resolve_fx_rate", _deterministic_resolve_fx_rate)
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("1000.00"), currency="USD", received_at=date(2026, 9, 8),
                source="freelance",
            ),
            user_id=user_id,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Hotel", amount=Decimal("100.00"), currency="USD",
                expense_date=date(2026, 9, 9),
            ),
            user_id=user_id,
        )

        def fx_must_not_be_resolved(**kwargs):
            raise AssertionError("analytics reads must never resolve FX")

        monkeypatch.setattr(fx_service, "resolve_fx_rate", fx_must_not_be_resolved)
        ecb_get = MagicMock()
        nbu_get = MagicMock()
        monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_get)
        monkeypatch.setattr(fx_nbu_provider.httpx, "get", nbu_get)

        overview = analytics_service.get_financial_overview(
            db_session=db_session, user_id=user_id, year=2026, month=9, as_of=AS_OF,
        )
        trend = analytics_service.get_income_expense_trend(
            db_session=db_session, user_id=user_id, count=2, as_of=AS_OF,
        )

        assert overview.income_total == Decimal("900.00")
        assert overview.expense_total == Decimal("90.00")
        assert overview.net_flow == Decimal("810.00")
        assert trend.buckets[0].income_total == Decimal("900.00")
        ecb_get.assert_not_called()
        nbu_get.assert_not_called()
    finally:
        db_session.close()


# Tests (C) unresolved rows stored in the database - a legacy Expense with
# no snapshot and an Income snapshotted in another base currency - are
# excluded and counted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both are counted as unresolved.
def test_overview_unresolved_rows_against_database(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            ExpenseModel(
                user_id=user_id, category_id=None, title="Legacy USD", amount=Decimal("999.00"),
                currency="USD", expense_date=date(2026, 9, 20), source="manual",
            )
        )
        db_session.add(
            IncomeModel(
                user_id=user_id, amount=Decimal("100.00"), currency="GBP",
                received_at=date(2026, 9, 21), source="gift",
                base_amount=Decimal("115.00"), base_currency="USD", fx_rate=Decimal("1.15000000"),
                fx_rate_date=date(2026, 9, 21), fx_source="ecb",
            )
        )
        db_session.commit()
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("400.00"), currency="EUR", received_at=date(2026, 9, 22),
                source="salary",
            ),
            user_id=user_id,
        )

        overview = analytics_service.get_financial_overview(
            db_session=db_session, user_id=user_id, year=2026, month=9, as_of=AS_OF,
        )

        assert overview.income_total == Decimal("400.00")
        assert (overview.income_count, overview.unresolved_income_count) == (1, 1)
        assert overview.expense_total == Decimal("0.00")
        assert (overview.expense_count, overview.unresolved_expense_count) == (0, 1)
        assert overview.data_status == "incomplete_data"
    finally:
        db_session.close()


# Tests (F) user isolation against the database: another user's resolved
# Income/Expenses and unresolved rows in the same month never affect the
# requesting user's totals, counts, data_status, or trend.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the user's own record counts.
def test_overview_and_trend_are_user_scoped_against_database(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("8000.00"), currency="EUR", received_at=date(2026, 9, 1),
                source="salary",
            ),
            user_id=other_user_id,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Other", amount=Decimal("700.00"), currency="EUR",
                expense_date=date(2026, 9, 2),
            ),
            user_id=other_user_id,
        )
        db_session.add(
            ExpenseModel(
                user_id=other_user_id, category_id=None, title="Other legacy",
                amount=Decimal("5.00"), currency="USD", expense_date=date(2026, 9, 3),
                source="manual",
            )
        )
        db_session.commit()
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Mine", amount=Decimal("12.00"), currency="EUR",
                expense_date=date(2026, 9, 4),
            ),
            user_id=user_id,
        )

        overview = analytics_service.get_financial_overview(
            db_session=db_session, user_id=user_id, year=2026, month=9, as_of=AS_OF,
        )
        september = analytics_service.get_income_expense_trend(
            db_session=db_session, user_id=user_id, count=2, as_of=AS_OF,
        ).buckets[0]

        for figures in (overview, september):
            assert figures.income_total == Decimal("0.00")
            assert figures.expense_total == Decimal("12.00")
            assert (figures.income_count, figures.expense_count) == (0, 1)
            assert figures.unresolved_expense_count == 0
        assert overview.data_status == "complete_data"
    finally:
        db_session.close()
