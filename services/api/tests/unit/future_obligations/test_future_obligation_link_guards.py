from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.modules.future_obligations import future_obligation_link_repository, future_obligation_link_service
from app.modules.future_obligations.future_obligation_errors import (
    ExpenseLinkedToFutureObligationError,
    FutureObligationHasLinkedOccurrencesError,
)
from app.modules.future_obligations.future_obligation_link_service import is_scheduled_occurrence

# VF-GOALS-PLANNING-002C2: the pure rules behind the guards. The repositories are faked, so
# these tests need no database; the integration tests exercise the same rules end to end.

TODAY = date(2026, 11, 16)
SESSION: Any = object()
USER = uuid4()


def _expense(amount: str = "950.00", currency: str = "EUR", expense_date: date = date(2026, 11, 10)) -> Any:
    return SimpleNamespace(id=uuid4(), amount=Decimal(amount), currency=currency, expense_date=expense_date)


def _obligation(**over: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "schedule": "monthly",
        "amount": Decimal("950.00"),
        "currency": "EUR",
        "first_due_date": date(2026, 10, 31),
        "final_due_date": None,
    }
    values.update(over)

    return SimpleNamespace(**values)


def _linked(monkeypatch: MonkeyPatch, *due_dates: date) -> None:
    link = SimpleNamespace(due_date=due_dates[0] if due_dates else date(2026, 11, 30))
    monkeypatch.setattr(future_obligation_link_repository, "get_by_expense", lambda *a, **k: link)
    monkeypatch.setattr(
        future_obligation_link_repository,
        "list_for_obligation",
        lambda *a, **k: [SimpleNamespace(due_date=due) for due in due_dates],
    )


def _expense_change(expense: Any, **final: Any) -> None:
    future_obligation_link_service.ensure_expense_change_allowed(
        SESSION,
        USER,
        expense,
        final_amount=final.get("amount", expense.amount),
        final_currency=final.get("currency", expense.currency),
        final_expense_date=final.get("expense_date", expense.expense_date),
        today=TODAY,
    )


class TestScheduledOccurrence:
    @pytest.mark.parametrize(
        ("first", "due", "expected"),
        [
            (date(2026, 1, 31), date(2027, 2, 28), True),  # the clamp of a "31st" bill
            (date(2026, 1, 31), date(2027, 2, 27), False),
            (date(2026, 1, 31), date(2027, 3, 31), True),  # the anchor is never lost
            (date(2027, 1, 31), date(2028, 2, 29), True),  # leap year clamp
            (date(2027, 1, 31), date(2028, 2, 28), False),
            (date(2026, 10, 30), date(2026, 11, 30), True),
            (date(2026, 10, 31), date(2026, 9, 30), False),  # before the first due date
        ],
    )
    def test_monthly_dates_are_the_clamped_anchor_day(self, first: date, due: date, expected: bool) -> None:
        assert is_scheduled_occurrence("monthly", first, None, due) is expected

    def test_a_monthly_bill_ends_after_its_final_due_date_inclusive(self) -> None:
        assert is_scheduled_occurrence("monthly", date(2026, 10, 31), date(2027, 1, 31), date(2027, 1, 31))
        assert not is_scheduled_occurrence("monthly", date(2026, 10, 31), date(2027, 1, 31), date(2027, 2, 28))

    def test_a_one_time_bill_has_only_its_own_date(self) -> None:
        assert is_scheduled_occurrence("one_time", date(2026, 12, 15), None, date(2026, 12, 15))
        assert not is_scheduled_occurrence("one_time", date(2026, 12, 15), None, date(2027, 1, 15))


class TestExpenseGuard:
    def test_an_unlinked_expense_may_change_freely(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(future_obligation_link_repository, "get_by_expense", lambda *a, **k: None)

        _expense_change(_expense(), amount=Decimal("1.00"), currency="USD", expense_date=date(2030, 1, 1))
        future_obligation_link_service.ensure_expense_can_be_deleted(SESSION, USER, uuid4())

    @pytest.mark.parametrize(
        "change",
        [{"amount": Decimal("951.00")}, {"currency": "USD"}, {"expense_date": date(2026, 11, 17)}],
        ids=["amount", "currency", "date_after_today"],
    )
    def test_a_linked_expense_cannot_change_what_the_link_depends_on(self, monkeypatch: MonkeyPatch, change: dict[str, Any]) -> None:
        _linked(monkeypatch)

        with pytest.raises(ExpenseLinkedToFutureObligationError):
            _expense_change(_expense(), **change)

    def test_a_linked_expense_keeps_every_other_freedom(self, monkeypatch: MonkeyPatch) -> None:
        _linked(monkeypatch)

        _expense_change(_expense())  # nothing financial changes
        _expense_change(_expense(), amount=Decimal("950"))  # the same value, written differently
        _expense_change(_expense(), expense_date=date(2026, 11, 16))  # today is allowed
        _expense_change(_expense(), expense_date=date(2026, 1, 2))  # so is any earlier date

    def test_a_linked_expense_cannot_be_deleted(self, monkeypatch: MonkeyPatch) -> None:
        _linked(monkeypatch)

        with pytest.raises(ExpenseLinkedToFutureObligationError):
            future_obligation_link_service.ensure_expense_can_be_deleted(SESSION, USER, uuid4())


class TestObligationGuard:
    def _check(self, obligation: Any, **final: Any) -> None:
        future_obligation_link_service.ensure_obligation_change_allowed(
            SESSION,
            USER,
            obligation,
            final_amount=final.get("amount", obligation.amount),
            final_currency=final.get("currency", obligation.currency),
            final_first_due_date=final.get("first", obligation.first_due_date),
            final_final_due_date=final.get("final", obligation.final_due_date),
        )

    def test_an_obligation_without_links_may_change_freely(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(future_obligation_link_repository, "list_for_obligation", lambda *a, **k: [])

        self._check(_obligation(), amount=Decimal("1.00"), currency="USD", first=date(2026, 1, 1), final=date(2026, 2, 1))

    @pytest.mark.parametrize(
        "change",
        [
            {"amount": Decimal("960.00")},
            {"currency": "USD"},
            {"first": date(2026, 10, 15)},  # anchor day 15: Nov 30 is no longer a due date
            {"final": date(2026, 10, 31)},  # ends before the linked date
        ],
        ids=["amount", "currency", "anchor_day", "ends_before_linked_date"],
    )
    def test_a_change_that_strands_a_link_is_refused(self, monkeypatch: MonkeyPatch, change: dict[str, Any]) -> None:
        _linked(monkeypatch, date(2026, 11, 30))

        with pytest.raises(FutureObligationHasLinkedOccurrencesError):
            self._check(_obligation(), **change)

    def test_every_link_is_checked_not_only_the_first(self, monkeypatch: MonkeyPatch) -> None:
        _linked(monkeypatch, date(2026, 11, 30), date(2027, 2, 28))

        self._check(_obligation())  # the 31st anchor keeps both
        with pytest.raises(FutureObligationHasLinkedOccurrencesError):
            self._check(_obligation(), final=date(2027, 1, 31))  # ends before the Feb 28 link

    def test_changes_that_keep_every_link_valid_are_allowed(self, monkeypatch: MonkeyPatch) -> None:
        _linked(monkeypatch, date(2026, 11, 30))

        self._check(_obligation(), amount=Decimal("950"))  # same value
        self._check(_obligation(), first=date(2026, 8, 31))  # starts earlier on the same anchor
        self._check(_obligation(), first=date(2026, 10, 30))  # the 30th is also November's clamp
        self._check(_obligation(), final=date(2027, 6, 30))  # ends later
