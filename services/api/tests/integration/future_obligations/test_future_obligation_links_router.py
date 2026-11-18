from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.main import app
from app.modules.expenses import expenses_service
from app.modules.future_obligations import future_obligation_link_service, future_obligation_service
from tests.helpers import auth_headers, create_account

# VF-GOALS-PLANNING-002C2: manual reconciliation of a bill occurrence with an existing
# Expense. A link is relationship metadata the user chose: it creates no Expense,
# posts nothing to an Account and changes no figure. "Today" is frozen at 2026-11-16,
# so every window and date below is exact.
#
# The running example is the rent: 950.00 EUR, monthly, first due 2026-10-31 (anchor
# day 31), so its occurrences are Oct 31, Nov 30, Dec 31, Jan 31, Feb 28 (2027), ...

TODAY = date(2026, 11, 16)
BASE = "/api/v1/future-obligations"


def _freeze(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(day.year, day.month, day.day)

    for module in (future_obligation_service, future_obligation_link_service, expenses_service):
        monkeypatch.setattr(module, "date", FrozenDate)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, TODAY)


def _obligation(client: TestClient, user: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Rent",
        "schedule": "monthly",
        "amount": "950.00",
        "currency": "EUR",
        "first_due_date": "2026-10-31",
    }
    body.update(over)
    response = client.post(BASE, headers=auth_headers(user), json=body)

    assert response.status_code == 201, response.text

    return response.json()


def _expense(client: TestClient, user: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Rent payment",
        "amount": "950.00",
        "currency": "EUR",
        "expense_date": "2026-11-10",
        "source": "manual",
    }
    body.update(over)
    response = client.post("/api/v1/expenses", headers=auth_headers(user), json=body)

    assert response.status_code == 201, response.text

    return response.json()


def _link(client: TestClient, user: str, obligation_id: str, due_date: str, expense_id: str):
    return client.post(
        f"{BASE}/{obligation_id}/occurrence-links",
        headers=auth_headers(user),
        json={"due_date": due_date, "expense_id": expense_id},
    )


def _linked(client: TestClient, user: str, obligation_id: str, due_date: str, expense_id: str) -> dict[str, Any]:
    response = _link(client, user, obligation_id, due_date, expense_id)

    assert response.status_code == 201, response.text

    return response.json()


def _unlink(client: TestClient, user: str, obligation_id: str, link_id: str):
    return client.delete(f"{BASE}/{obligation_id}/occurrence-links/{link_id}", headers=auth_headers(user))


def _overview(client: TestClient, user: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/reconciliation", headers=auth_headers(user))

    assert response.status_code == 200, response.text

    return response.json()


def _occurrence(overview: dict[str, Any], obligation_id: str, due_date: str) -> Optional[dict[str, Any]]:
    for item in overview["occurrences"]:
        if item["obligation_id"] == obligation_id and item["due_date"] == due_date:
            return item

    return None


def _linked_dates(overview: dict[str, Any], obligation_id: str) -> list[str]:
    return [
        item["due_date"]
        for item in overview["occurrences"]
        if item["obligation_id"] == obligation_id and item["linked_expense"] is not None
    ]


def _count_links(user: str) -> int:
    with SessionLocal() as session:
        return session.execute(
            text("SELECT count(*) FROM future_obligation_expense_links WHERE user_id = :u"), {"u": user}
        ).scalar_one()


def _error_code(response: Any) -> str:
    return response.json()["code"]


class TestLinkAndUnlink:
    def test_a_link_is_created_shown_and_removed_without_touching_the_expense(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)
        before = client.get("/api/v1/expenses", headers=auth_headers(user)).json()

        created = _link(client, user, rent["id"], "2026-11-30", expense["id"])

        assert created.status_code == 201
        link = created.json()
        assert set(link) == {"id", "obligation_id", "due_date", "expense_id", "created_at"}
        assert (link["obligation_id"], link["due_date"], link["expense_id"]) == (rent["id"], "2026-11-30", expense["id"])
        shown = _occurrence(_overview(client, user), rent["id"], "2026-11-30")
        assert shown is not None and shown["linked_expense"] is not None
        assert shown["linked_expense"]["link_id"] == link["id"]
        assert shown["linked_expense"]["expense_id"] == expense["id"]
        assert shown["linked_expense"]["expense_date"] == "2026-11-10"
        assert shown["amount"] == "950.00" and shown["currency"] == "EUR"

        removed = _unlink(client, user, rent["id"], link["id"])

        assert removed.status_code == 204
        after_unlink = _occurrence(_overview(client, user), rent["id"], "2026-11-30")
        assert after_unlink is not None and after_unlink["linked_expense"] is None
        # The Expense and the obligation are exactly as they were.
        assert client.get("/api/v1/expenses", headers=auth_headers(user)).json() == before
        assert client.get(f"{BASE}/{rent['id']}", headers=auth_headers(user)).json() == rent

    def test_repeating_the_identical_link_is_idempotent(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)
        first = _link(client, user, rent["id"], "2026-11-30", expense["id"])

        again = _link(client, user, rent["id"], "2026-11-30", expense["id"])

        assert (first.status_code, again.status_code) == (201, 200)
        assert again.json() == first.json()
        assert _count_links(user) == 1

    def test_removing_a_missing_or_already_removed_link_is_a_stable_404(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        link = _linked(client, user, rent["id"], "2026-11-30", _expense(client, user)["id"])
        assert _unlink(client, user, rent["id"], link["id"]).status_code == 204

        again = _unlink(client, user, rent["id"], link["id"])

        assert again.status_code == 404 and _error_code(again) == "future_obligation_link_not_found"

    def test_the_link_id_must_belong_to_the_obligation_in_the_path(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent, phone = _obligation(client, user), _obligation(client, user, name="Phone", amount="30.00")
        link = _linked(client, user, rent["id"], "2026-11-30", _expense(client, user)["id"])

        wrong = _unlink(client, user, phone["id"], link["id"])

        assert wrong.status_code == 404 and _count_links(user) == 1


class TestOccurrenceIdentity:
    def test_each_month_is_its_own_occurrence(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        december = _expense(client, user, title="Rent December", expense_date="2026-11-12")
        # December 31 is linked (recorded early). Nothing else changes.
        _linked(client, user, rent["id"], "2026-12-31", december["id"])

        overview = _overview(client, user)

        assert _linked_dates(overview, rent["id"]) == ["2026-12-31"]
        for other in ("2026-11-30", "2027-01-31", "2027-02-28"):
            shown = _occurrence(overview, rent["id"], other)
            assert shown is not None and shown["linked_expense"] is None, other

    def test_unlinking_one_month_leaves_the_others_linked(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        october = _linked(client, user, rent["id"], "2026-10-31", _expense(client, user, expense_date="2026-11-03")["id"])
        _linked(client, user, rent["id"], "2026-11-30", _expense(client, user, expense_date="2026-11-14")["id"])

        _unlink(client, user, rent["id"], october["id"])

        assert _linked_dates(_overview(client, user), rent["id"]) == ["2026-11-30"]

    def test_the_expense_date_need_not_match_the_due_date(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        early = _expense(client, user, title="Paid early", expense_date="2026-11-02")
        late = _expense(client, user, title="Paid late", expense_date="2026-11-10")

        assert _link(client, user, rent["id"], "2026-11-30", early["id"]).status_code == 201  # before the due date
        assert _link(client, user, rent["id"], "2026-10-31", late["id"]).status_code == 201  # after the due date

    def test_a_one_time_obligation_has_exactly_one_occurrence(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        insurance = _obligation(client, user, name="Insurance", schedule="one_time", amount="480.00", first_due_date="2026-12-15")
        expense = _expense(client, user, title="Insurance", amount="480.00", expense_date="2026-11-10")

        wrong_day = _link(client, user, insurance["id"], "2026-12-14", expense["id"])
        next_month = _link(client, user, insurance["id"], "2027-01-15", expense["id"])
        right = _link(client, user, insurance["id"], "2026-12-15", expense["id"])

        assert (wrong_day.status_code, next_month.status_code, right.status_code) == (422, 422, 201)
        assert _error_code(wrong_day) == _error_code(next_month) == "future_obligation_occurrence_invalid"

    def test_a_month_end_due_date_is_the_clamped_one_not_the_anchor_day(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user, first_due_date="2026-01-31")
        expense = _expense(client, user, expense_date="2026-11-01")

        feb_27 = _link(client, user, rent["id"], "2027-02-27", expense["id"])
        feb_28 = _link(client, user, rent["id"], "2027-02-28", expense["id"])

        assert feb_27.status_code == 422 and _error_code(feb_27) == "future_obligation_occurrence_invalid"
        assert feb_28.status_code == 201

    def test_the_leap_day_is_an_occurrence_only_in_a_leap_year(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user, first_due_date="2027-01-31")
        expense = _expense(client, user, expense_date="2026-11-01")

        no_leap_day = _link(client, user, rent["id"], "2027-02-29", expense["id"])  # not a calendar date
        not_the_clamp = _link(client, user, rent["id"], "2028-02-28", expense["id"])  # 2028 is a leap year: the 29th
        the_clamp = _link(client, user, rent["id"], "2028-02-29", expense["id"])

        assert no_leap_day.status_code == 422
        assert not_the_clamp.status_code == 422 and _error_code(not_the_clamp) == "future_obligation_occurrence_invalid"
        assert the_clamp.status_code == 201

    def test_dates_outside_the_schedule_are_refused(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user, final_due_date="2027-03-31")
        expense = _expense(client, user, expense_date="2026-11-01")

        for bad in ("2026-09-30", "2027-04-30", "2026-11-29", "1999-12-31"):
            response = _link(client, user, rent["id"], bad, expense["id"])

            assert response.status_code == 422, bad

        assert _count_links(user) == 0


class TestLinkValidation:
    def test_the_amount_must_be_exactly_equal(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)

        for amount in ("949.99", "950.01", "95.00", "9500.00"):
            response = _link(client, user, rent["id"], "2026-11-30", _expense(client, user, amount=amount)["id"])

            assert response.status_code == 422 and _error_code(response) == "future_obligation_link_amount_mismatch", amount

        # Whole numbers and trailing zeros are the same Decimal.
        assert _link(client, user, rent["id"], "2026-11-30", _expense(client, user, amount="950")["id"]).status_code == 201

    def test_the_currency_must_be_identical_and_is_never_converted(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        usd_bill = _obligation(client, user, currency="USD")
        eur_expense = _expense(client, user)  # same number, different currency

        response = _link(client, user, usd_bill["id"], "2026-11-30", eur_expense["id"])

        assert response.status_code == 422 and _error_code(response) == "future_obligation_link_currency_mismatch"

    def test_an_expense_dated_after_today_cannot_be_linked(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        tomorrow = _expense(client, user, expense_date="2026-11-17")
        today = _expense(client, user, expense_date="2026-11-16")

        refused = _link(client, user, rent["id"], "2026-11-30", tomorrow["id"])

        assert refused.status_code == 422 and _error_code(refused) == "future_obligation_link_expense_date_invalid"
        assert _link(client, user, rent["id"], "2026-11-30", today["id"]).status_code == 201

    def test_the_body_accepts_nothing_else(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        for extra in ({"user_id": str(uuid4())}, {"amount": "1.00"}, {"id": str(uuid4())}):
            response = client.post(
                f"{BASE}/{rent['id']}/occurrence-links",
                headers=auth_headers(user),
                json={"due_date": "2026-11-30", "expense_id": expense["id"], **extra},
            )

            assert response.status_code == 422, extra

    def test_an_existing_link_is_never_replaced_or_reassigned(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        first = _expense(client, user, title="First")
        second = _expense(client, user, title="Second")
        link = _linked(client, user, rent["id"], "2026-11-30", first["id"])

        other_expense = _link(client, user, rent["id"], "2026-11-30", second["id"])  # occurrence taken
        other_occurrence = _link(client, user, rent["id"], "2026-12-31", first["id"])  # expense taken

        assert other_expense.status_code == 409
        assert _error_code(other_expense) == "future_obligation_link_occurrence_already_linked"
        assert other_occurrence.status_code == 409
        assert _error_code(other_occurrence) == "future_obligation_link_expense_already_linked"
        assert _linked_dates(_overview(client, user), rent["id"]) == ["2026-11-30"]
        shown = _occurrence(_overview(client, user), rent["id"], "2026-11-30")
        assert shown is not None and shown["linked_expense"]["link_id"] == link["id"]
        # Removing the link frees both, and only then can they be linked again.
        _unlink(client, user, rent["id"], link["id"])
        assert _link(client, user, rent["id"], "2026-11-30", second["id"]).status_code == 201

    def test_one_expense_cannot_be_linked_to_another_obligation_too(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        parking = _obligation(client, user, name="Parking")
        expense = _expense(client, user)
        _linked(client, user, rent["id"], "2026-11-30", expense["id"])

        response = _link(client, user, parking["id"], "2026-11-30", expense["id"])

        assert response.status_code == 409


class TestOwnership:
    def test_another_users_records_are_not_found_and_leak_nothing(self, client: TestClient, clean_database: None) -> None:
        owner, stranger = str(uuid4()), str(uuid4())
        rent = _obligation(client, owner)
        expense = _expense(client, owner)
        link = _linked(client, owner, rent["id"], "2026-11-30", expense["id"])
        mine = _obligation(client, stranger)
        my_expense = _expense(client, stranger)

        foreign_obligation = _link(client, stranger, rent["id"], "2026-11-30", my_expense["id"])
        foreign_expense = _link(client, stranger, mine["id"], "2026-11-30", expense["id"])
        foreign_unlink = _unlink(client, stranger, rent["id"], link["id"])
        foreign_candidates = client.get(
            f"{BASE}/{rent['id']}/occurrence-candidates", headers=auth_headers(stranger), params={"due_date": "2026-11-30"}
        )

        assert (foreign_obligation.status_code, _error_code(foreign_obligation)) == (404, "future_obligation_not_found")
        assert (foreign_expense.status_code, _error_code(foreign_expense)) == (404, "expense_not_found")
        assert (foreign_unlink.status_code, _error_code(foreign_unlink)) == (404, "future_obligation_link_not_found")
        assert foreign_candidates.status_code == 404
        strangers_view = _overview(client, stranger)["occurrences"]
        assert strangers_view and all(item["obligation_id"] == mine["id"] for item in strangers_view)
        assert all(item["linked_expense"] is None for item in strangers_view)
        assert _count_links(owner) == 1 and _count_links(stranger) == 0

    def test_the_endpoints_require_authentication(self, client: TestClient, clean_database: None) -> None:
        anyone = str(uuid4())

        for response in (
            client.get(f"{BASE}/reconciliation"),
            client.post(f"{BASE}/{anyone}/occurrence-links", json={"due_date": "2026-11-30", "expense_id": anyone}),
            client.delete(f"{BASE}/{anyone}/occurrence-links/{anyone}"),
            client.get(f"{BASE}/{anyone}/occurrence-candidates", params={"due_date": "2026-11-30"}),
        ):
            assert response.status_code in (401, 403)


class TestExpenseStaysConsistentWithItsLink:
    def _linked_rent(self, client: TestClient, user: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        rent = _obligation(client, user)
        expense = _expense(client, user)

        return rent, expense, _linked(client, user, rent["id"], "2026-11-30", expense["id"])

    def _patch(self, client: TestClient, user: str, expense_id: str, **fields: Any):
        return client.patch(f"/api/v1/expenses/{expense_id}", headers=auth_headers(user), json=fields)

    def test_a_linked_expense_cannot_be_deleted_until_it_is_unlinked(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent, expense, link = self._linked_rent(client, user)

        refused = client.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user))

        assert refused.status_code == 409 and _error_code(refused) == "expense_linked_to_future_obligation"
        assert client.get("/api/v1/expenses", headers=auth_headers(user)).json()[0]["id"] == expense["id"]
        _unlink(client, user, rent["id"], link["id"])
        assert client.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user)).status_code == 204

    @pytest.mark.parametrize(
        "change",
        [{"amount": "951.00"}, {"currency": "USD"}, {"expense_date": "2026-11-17"}],
        ids=["amount", "currency", "date_after_today"],
    )
    def test_a_change_that_would_invalidate_the_link_is_a_controlled_conflict(
        self, client: TestClient, clean_database: None, change: dict[str, Any]
    ) -> None:
        user = str(uuid4())
        _, expense, _ = self._linked_rent(client, user)

        refused = self._patch(client, user, expense["id"], **change)

        assert refused.status_code == 409 and _error_code(refused) == "expense_linked_to_future_obligation"
        stored = [e for e in client.get("/api/v1/expenses", headers=auth_headers(user)).json() if e["id"] == expense["id"]][0]
        assert (stored["amount"], stored["currency"], stored["expense_date"]) == ("950.00", "EUR", "2026-11-10")

    def test_edits_that_keep_the_link_valid_stay_possible(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent, expense, _ = self._linked_rent(client, user)

        renamed = self._patch(client, user, expense["id"], title="November rent", description="paid by transfer")
        same_values = self._patch(client, user, expense["id"], amount="950", currency="EUR")
        earlier = self._patch(client, user, expense["id"], expense_date="2026-11-03")

        assert (renamed.status_code, same_values.status_code, earlier.status_code) == (200, 200, 200)
        assert earlier.json()["expense_date"] == "2026-11-03"
        shown = _occurrence(_overview(client, user), rent["id"], "2026-11-30")
        assert shown is not None and shown["linked_expense"]["title"] == "November rent"
        assert shown["linked_expense"]["expense_date"] == "2026-11-03"

    def test_an_unlinked_expense_is_unrestricted(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        expense = _expense(client, user)

        assert self._patch(client, user, expense["id"], amount="1.00", expense_date="2026-11-20").status_code == 200
        assert client.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user)).status_code == 204


class TestObligationStaysConsistentWithItsLinks:
    def _rent_with_link(self, client: TestClient, user: str) -> tuple[dict[str, Any], dict[str, Any]]:
        rent = _obligation(client, user)

        return rent, _linked(client, user, rent["id"], "2026-11-30", _expense(client, user)["id"])

    def _patch(self, client: TestClient, user: str, obligation_id: str, **fields: Any):
        return client.patch(f"{BASE}/{obligation_id}", headers=auth_headers(user), json=fields)

    @pytest.mark.parametrize(
        "change",
        [
            {"amount": "960.00"},
            {"currency": "USD"},
            {"first_due_date": "2026-10-15"},  # anchored on the 15th, the linked Nov 30 is no longer a due date
            {"final_due_date": "2026-10-31"},  # the bill ends before the linked Nov 30
        ],
        ids=["amount", "currency", "anchor_day", "ends_before_linked_date"],
    )
    def test_a_change_that_would_strand_a_linked_occurrence_is_a_controlled_conflict(
        self, client: TestClient, clean_database: None, change: dict[str, Any]
    ) -> None:
        user = str(uuid4())
        rent, _ = self._rent_with_link(client, user)

        response = self._patch(client, user, rent["id"], **change)

        assert response.status_code == 409 and _error_code(response) == "future_obligation_has_linked_occurrences"
        stored = client.get(f"{BASE}/{rent['id']}", headers=auth_headers(user)).json()
        assert {key: stored[key] for key in change} == {key: rent[key] for key in change}
        assert _count_links(user) == 1

    def test_a_change_that_keeps_every_link_valid_is_allowed(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent, _ = self._rent_with_link(client, user)

        results = [
            self._patch(client, user, rent["id"], name="Flat rent", description="Landlord"),
            self._patch(client, user, rent["id"], amount="950", currency="EUR"),  # same values
            self._patch(client, user, rent["id"], final_due_date="2027-06-30"),  # the end moves later
            self._patch(client, user, rent["id"], first_due_date="2026-08-31"),  # starts earlier on the same anchor
            self._patch(client, user, rent["id"], first_due_date="2026-10-30"),  # the 30th is also November's clamp
        ]

        assert [r.status_code for r in results] == [200, 200, 200, 200, 200]

    def test_archiving_keeps_the_history_and_a_restore_brings_the_occurrences_back(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent, link = self._rent_with_link(client, user)
        other = _linked(client, user, rent["id"], "2026-12-31", _expense(client, user, expense_date="2026-11-10")["id"])

        archived = self._patch(client, user, rent["id"], status="archived")

        assert archived.status_code == 200
        overview = _overview(client, user)
        # Only the linked occurrences remain visible, and they still say who they are.
        assert [(i["due_date"], i["obligation_status"]) for i in overview["occurrences"]] == [
            ("2026-11-30", "archived"),
            ("2026-12-31", "archived"),
        ]
        assert _count_links(user) == 2
        # An archived obligation contributes no occurrences, so nothing new can be linked.
        late = _link(client, user, rent["id"], "2027-01-31", _expense(client, user, expense_date="2026-11-11")["id"])
        assert late.status_code == 422 and _error_code(late) == "future_obligation_occurrence_invalid"
        # Removing a link of an archived obligation still works.
        assert _unlink(client, user, rent["id"], other["id"]).status_code == 204

        restored = self._patch(client, user, rent["id"], status="active")

        assert restored.status_code == 200
        assert _linked_dates(_overview(client, user), rent["id"]) == ["2026-11-30"]
        assert link["id"] == _occurrence(_overview(client, user), rent["id"], "2026-11-30")["linked_expense"]["link_id"]


class TestOverview:
    def test_the_window_is_three_past_months_the_current_month_and_the_planning_horizon(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user, first_due_date="2026-01-31")

        overview = _overview(client, user)

        assert (overview["as_of"], overview["window_start"], overview["window_end"]) == ("2026-11-16", "2026-08-01", "2027-10-31")
        dates = [item["due_date"] for item in overview["occurrences"] if item["obligation_id"] == rent["id"]]
        assert dates[0] == "2026-08-31" and dates[-1] == "2027-10-31" and len(dates) == 15
        assert "2027-02-28" in dates
        past = {item["due_date"] for item in overview["occurrences"] if item["is_past"]}
        assert past == {"2026-08-31", "2026-09-30", "2026-10-31"}  # Nov 30 is after Nov 16

    def test_the_overview_is_ordered_and_covers_one_time_bills_inside_the_window_only(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        _obligation(client, user, name="Old", schedule="one_time", first_due_date="2026-07-15")
        _obligation(client, user, name="Recent", schedule="one_time", first_due_date="2026-09-10")
        _obligation(client, user, name="Far", schedule="one_time", first_due_date="2027-11-01")
        _obligation(client, user, name="Near", schedule="one_time", first_due_date="2027-10-31")

        occurrences = _overview(client, user)["occurrences"]

        assert [(o["name"], o["is_past"]) for o in occurrences] == [("Recent", True), ("Near", False)]

    def test_the_overview_never_changes_the_upcoming_bills_projection(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        _obligation(client, user, name="Insurance", schedule="one_time", amount="480.00", first_due_date="2026-12-15")
        before = client.get(f"{BASE}/upcoming", headers=auth_headers(user)).json()

        link = _linked(client, user, rent["id"], "2026-11-30", _expense(client, user)["id"])
        with_link = client.get(f"{BASE}/upcoming", headers=auth_headers(user)).json()
        _unlink(client, user, rent["id"], link["id"])
        after = client.get(f"{BASE}/upcoming", headers=auth_headers(user)).json()

        # A linked occurrence still counts in the schedule totals: nothing is subtracted.
        assert before == with_link == after

    def test_an_occurrence_without_a_link_says_nothing_about_payment(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _obligation(client, user)

        item = _overview(client, user)["occurrences"][0]

        assert item["linked_expense"] is None
        assert not any("paid" in key or "unpaid" in key or "overdue" in key for key in item)


class TestCandidates:
    def _candidates(self, client: TestClient, user: str, obligation_id: str, due_date: str = "2026-11-30"):
        return client.get(
            f"{BASE}/{obligation_id}/occurrence-candidates", headers=auth_headers(user), params={"due_date": due_date}
        )

    def test_only_exactly_matching_unlinked_recorded_expenses_are_offered_and_the_rest_are_counted(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        good_new = _expense(client, user, title="Rent Nov", expense_date="2026-11-10")
        good_old = _expense(client, user, title="Rent Oct", expense_date="2026-10-05")
        _expense(client, user, title="Other amount", amount="949.99")
        _expense(client, user, title="Future", expense_date="2026-11-20")
        taken = _expense(client, user, title="Already linked", expense_date="2026-09-03")
        _linked(client, user, _obligation(client, user, name="Old rent", first_due_date="2026-09-30")["id"], "2026-09-30", taken["id"])
        usd_bill = _obligation(client, user, name="Dollar bill", currency="USD")

        response = self._candidates(client, user, rent["id"])

        assert response.status_code == 200
        body = response.json()
        assert [c["expense_id"] for c in body["candidates"]] == [good_new["id"], good_old["id"]]  # newest first
        assert body["excluded"] == {"different_currency": 0, "different_amount": 1, "already_linked": 1, "dated_in_future": 1}
        assert (body["amount"], body["currency"], body["candidate_limit"]) == ("950.00", "EUR", 50)
        # The same Expenses are all "a different currency" for a bill in dollars: nothing is converted.
        usd = self._candidates(client, user, usd_bill["id"]).json()
        assert usd["candidates"] == [] and usd["excluded"]["different_currency"] == 5

    def test_candidates_are_never_ranked_or_filtered_by_name(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        _expense(client, user, title="Groceries", expense_date="2026-11-01")
        _expense(client, user, title="Rent", expense_date="2026-11-02")

        titles = [c["title"] for c in self._candidates(client, user, rent["id"]).json()["candidates"]]

        assert titles == ["Rent", "Groceries"]  # by date only

    def test_an_invalid_occurrence_has_no_candidates(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)

        response = self._candidates(client, user, rent["id"], "2026-11-29")

        assert response.status_code == 422 and _error_code(response) == "future_obligation_occurrence_invalid"


def _digest(user: str, table: str) -> tuple[Any, ...]:
    with SessionLocal() as session:
        row = session.execute(
            text(f"SELECT count(*), md5(string_agg(t::text, ',' ORDER BY t.id::text)) FROM {table} t WHERE t.user_id = :u"),
            {"u": user},
        ).one()

        return tuple(row)


class TestNoFinancialSideEffects:
    LEDGER_TABLES = (
        "expenses",
        "income",
        "accounts",
        "account_transactions",
        "account_transfers",
        "goals",
        "goal_transactions",
        "budgets",
        "financial_events",
        "financial_rules",
        "future_obligations",
    )

    def test_linking_and_unlinking_change_no_ledger_row_and_create_nothing(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        account = create_account(client, user, opening_balance="2000.00", opening_balance_date="2026-01-01")
        rent = _obligation(client, user)
        expense = _expense(client, user, account_id=account["id"])  # an Expense that is also posted to an Account
        before = {table: _digest(user, table) for table in self.LEDGER_TABLES}
        balance_before = client.get(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user)).json()
        upcoming_before = client.get(f"{BASE}/upcoming", headers=auth_headers(user)).json()

        link = _linked(client, user, rent["id"], "2026-11-30", expense["id"])
        during = {table: _digest(user, table) for table in self.LEDGER_TABLES}
        _unlink(client, user, rent["id"], link["id"])
        after = {table: _digest(user, table) for table in self.LEDGER_TABLES}

        assert during == before == after
        assert client.get(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user)).json() == balance_before
        assert client.get(f"{BASE}/upcoming", headers=auth_headers(user)).json() == upcoming_before
        assert before["expenses"][0] == 1 and before["account_transactions"][0] >= 1  # the Expense is posted once, never twice

    def test_a_refused_link_writes_nothing(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user, amount="12.34")
        before = {table: _digest(user, table) for table in self.LEDGER_TABLES}

        assert _link(client, user, rent["id"], "2026-11-30", expense["id"]).status_code == 422

        assert {table: _digest(user, table) for table in self.LEDGER_TABLES} == before
        assert _count_links(user) == 0


def _run_together(*calls: Any) -> list[Any]:
    barrier = Barrier(len(calls))

    def run(call: Any) -> Any:
        with TestClient(app) as thread_client:
            barrier.wait(timeout=15)
            return call(thread_client)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [future.result(timeout=60) for future in [pool.submit(run, call) for call in calls]]


class TestConcurrency:
    def test_identical_concurrent_links_create_exactly_one(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        responses = _run_together(
            *[lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]) for _ in range(6)]
        )

        assert sorted(r.status_code for r in responses) == [200] * 5 + [201], [r.text for r in responses]
        assert len({r.json()["id"] for r in responses}) == 1 and _count_links(user) == 1

    def test_two_expenses_racing_for_one_occurrence_leave_exactly_one_link(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expenses = [_expense(client, user, title=f"Rent {i}") for i in range(4)]

        responses = _run_together(
            *[lambda c, e=e: _link(c, user, rent["id"], "2026-11-30", e["id"]) for e in expenses]
        )

        assert sorted(r.status_code for r in responses) == [201, 409, 409, 409], [r.text for r in responses]
        assert {_error_code(r) for r in responses if r.status_code == 409} == {"future_obligation_link_occurrence_already_linked"}
        assert _count_links(user) == 1

    def test_one_expense_racing_for_two_occurrences_is_linked_once(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        responses = _run_together(
            lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]),
            lambda c: _link(c, user, rent["id"], "2026-12-31", expense["id"]),
        )

        assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
        assert _count_links(user) == 1

    def test_a_link_and_a_delete_of_the_same_expense_never_leave_a_stale_link(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        link, delete = _run_together(
            lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]),
            lambda c: c.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user)),
        )

        with SessionLocal() as session:
            exists = session.execute(text("SELECT count(*) FROM expenses WHERE id = :i"), {"i": expense["id"]}).scalar_one()
        # Either the link won (the delete was refused) or the delete won (nothing to link):
        # never a link to a deleted Expense, never both succeeding.
        assert (link.status_code, delete.status_code, exists, _count_links(user)) in {(201, 409, 1, 1), (404, 204, 0, 0)}

    def test_a_link_and_an_amount_change_of_the_expense_never_leave_a_stale_link(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        link, patch = _run_together(
            lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]),
            lambda c: c.patch(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user), json={"amount": "960.00"}),
        )

        with SessionLocal() as session:
            amount = str(session.execute(text("SELECT amount FROM expenses WHERE id = :i"), {"i": expense["id"]}).scalar_one())
        assert (link.status_code, patch.status_code, amount, _count_links(user)) in {
            (201, 409, "950.00", 1),  # the link won: the change was refused
            (422, 200, "960.00", 0),  # the change won: the amounts no longer match
        }

    def test_a_link_and_an_amount_change_of_the_obligation_never_leave_a_stale_link(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        link, patch = _run_together(
            lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]),
            lambda c: c.patch(f"{BASE}/{rent['id']}", headers=auth_headers(user), json={"amount": "960.00"}),
        )

        with SessionLocal() as session:
            amount = str(session.execute(text("SELECT amount FROM future_obligations WHERE id = :i"), {"i": rent["id"]}).scalar_one())
        assert (link.status_code, patch.status_code, amount, _count_links(user)) in {
            (201, 409, "950.00", 1),
            (422, 200, "960.00", 0),
        }

    def test_busy_mixed_traffic_on_one_expense_and_obligation_never_deadlocks(
        self, client: TestClient, clean_database: None
    ) -> None:
        user = str(uuid4())
        rent = _obligation(client, user)
        expense = _expense(client, user)

        responses = _run_together(
            lambda c: _link(c, user, rent["id"], "2026-11-30", expense["id"]),
            lambda c: c.patch(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user), json={"title": "A"}),
            lambda c: c.patch(f"{BASE}/{rent['id']}", headers=auth_headers(user), json={"name": "B"}),
            lambda c: c.patch(f"{BASE}/{rent['id']}", headers=auth_headers(user), json={"status": "archived"}),
            lambda c: c.get(f"{BASE}/reconciliation", headers=auth_headers(user)),
            lambda c: c.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user)),
        )

        assert all(r.status_code < 500 for r in responses), [(r.status_code, r.text) for r in responses]
