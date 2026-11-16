from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import SessionLocal, engine
from app.main import app
from app.modules.financial_settings.financial_settings_models import UserFinancialSettingsModel
from app.modules.future_obligations import future_obligation_service
from tests.helpers import auth_headers, create_account, create_goal_transaction

# VF-GOALS-PLANNING-002C1: /api/v1/future-obligations. Authenticated, user-scoped,
# manually entered future obligations and their read-only 12-month projection.
# "Today" is frozen at 2026-11-16 so every date in a response is exact.

TODAY = date(2026, 11, 16)
BASE = "/api/v1/future-obligations"


def _freeze(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    class FrozenDate(date):
        @classmethod
        def today(cls) -> "FrozenDate":
            return cls(day.year, day.month, day.day)

    monkeypatch.setattr(future_obligation_service, "date", FrozenDate)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, TODAY)


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Car insurance",
        "schedule": "monthly",
        "amount": "120.00",
        "first_due_date": "2026-11-20",
    }
    body.update(over)

    return body


def _post(client: TestClient, user: str, **over: Any):
    return client.post(BASE, headers=auth_headers(user), json=_body(**over))


def _create(client: TestClient, user: str, **over: Any) -> dict[str, Any]:
    response = _post(client, user, **over)

    assert response.status_code == 201, response.text

    return response.json()


def _upcoming(client: TestClient, user: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/upcoming", headers=auth_headers(user))

    assert response.status_code == 200, response.text

    return response.json()


def _patch(client: TestClient, user: str, obligation_id: str, **fields: Any):
    return client.patch(f"{BASE}/{obligation_id}", headers=auth_headers(user), json=fields)


def _totals(body: dict[str, Any]) -> list[str]:
    return [month["base_currency_total"] for month in body["months"]]


class TestOneTimeObligation:
    def test_creates_and_returns_the_obligation(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())

        response = _post(client, user, name="Tax payment", schedule="one_time", amount="850.00", first_due_date="2027-01-31", description="Planned")
        body = response.json()

        assert response.status_code == 201, response.text
        assert body["name"] == "Tax payment" and body["schedule"] == "one_time"
        assert body["amount"] == "850.00" and body["currency"] == "EUR"
        assert (body["first_due_date"], body["final_due_date"]) == ("2027-01-31", None)
        assert (body["status"], body["description"], body["next_due_date"]) == ("active", "Planned", "2027-01-31")
        assert body["user_id"] == user and body["client_request_id"] is None
        assert body["id"] and body["created_at"] and body["updated_at"]

    def test_appears_once_in_the_month_of_its_due_date(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="Repair", schedule="one_time", amount="430.55", first_due_date="2027-02-14")

        body = _upcoming(client, user)

        assert [m["occurrence_count"] for m in body["months"]] == [0, 0, 0, 1] + [0] * 8
        assert body["months"][3]["occurrences"][0]["due_date"] == "2027-02-14"
        assert _totals(body)[3] == "430.55" and body["base_currency_window_total"] == "430.55"

    def test_a_final_due_date_is_rejected(self, client: TestClient, clean_database: None) -> None:
        response = _post(client, str(uuid4()), schedule="one_time", final_due_date="2027-05-01")

        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    def test_a_past_one_time_obligation_is_stored_but_has_no_upcoming_date(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, schedule="one_time", first_due_date="2026-11-15")

        assert created["next_due_date"] is None
        assert sum(m["occurrence_count"] for m in _upcoming(client, user)["months"]) == 0
        assert len(client.get(BASE, headers=auth_headers(user)).json()) == 1


class TestMonthlyObligation:
    def test_recurs_each_month_from_its_first_due_date(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, name="Rent", amount="950.00", first_due_date="2026-11-20")

        body = _upcoming(client, user)

        assert created["next_due_date"] == "2026-11-20"
        assert [m["occurrence_count"] for m in body["months"]] == [1] * 12
        assert _totals(body) == ["950.00"] * 12 and body["base_currency_window_total"] == "11400.00"
        assert [m["occurrences"][0]["due_date"] for m in body["months"][:3]] == ["2026-11-20", "2026-12-20", "2027-01-20"]

    def test_started_earlier_gives_only_upcoming_due_dates(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, first_due_date="2024-03-10")  # due the 10th: this month's is past

        body = _upcoming(client, user)

        assert created["next_due_date"] == "2026-12-10"
        assert body["months"][0]["occurrence_count"] == 0
        assert body["months"][1]["occurrences"][0]["due_date"] == "2026-12-10"
        assert sum(m["occurrence_count"] for m in body["months"]) == 11

    def test_due_today_is_included(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, first_due_date="2026-11-16")

        assert _upcoming(client, user)["months"][0]["occurrences"][0]["due_date"] == "2026-11-16"

    def test_an_optional_final_due_date_ends_the_recurrence(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, first_due_date="2026-11-20", final_due_date="2027-01-20")

        body = _upcoming(client, user)

        assert created["final_due_date"] == "2027-01-20"
        assert [m["occurrence_count"] for m in body["months"]] == [1, 1, 1] + [0] * 9

    def test_after_the_final_due_date_there_is_no_next_due_date(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, first_due_date="2025-01-05", final_due_date="2026-06-05")

        assert created["next_due_date"] is None
        assert sum(m["occurrence_count"] for m in _upcoming(client, user)["months"]) == 0

    def test_a_final_due_date_before_the_first_is_rejected(self, client: TestClient, clean_database: None) -> None:
        assert _post(client, str(uuid4()), first_due_date="2026-12-31", final_due_date="2026-12-30").status_code == 422

    def test_day_31_clamps_and_recovers_with_no_drift(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="End of month", first_due_date="2026-01-31")

        dates = [m["occurrences"][0]["due_date"] for m in _upcoming(client, user)["months"]]

        assert dates == [
            "2026-11-30", "2026-12-31", "2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30",
            "2027-05-31", "2027-06-30", "2027-07-31", "2027-08-31", "2027-09-30", "2027-10-31",
        ]

    def test_days_29_and_30_in_a_leap_february(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        _freeze(monkeypatch, date(2027, 12, 20))
        user = str(uuid4())
        _create(client, user, name="Twenty-nine", first_due_date="2027-01-29")
        _create(client, user, name="Thirty", first_due_date="2027-01-30")

        body = _upcoming(client, user)
        february = body["months"][2]

        assert february["period_end"] == "2028-02-29"
        assert {o["name"]: o["due_date"] for o in february["occurrences"]} == {"Twenty-nine": "2028-02-29", "Thirty": "2028-02-29"}
        assert body["months"][3]["occurrences"][0]["due_date"] == "2028-03-29"

    def test_a_non_leap_february_clamps_to_the_28th(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        _freeze(monkeypatch, date(2026, 12, 20))
        user = str(uuid4())
        _create(client, user, first_due_date="2026-12-29")

        assert _upcoming(client, user)["months"][2]["occurrences"][0]["due_date"] == "2027-02-28"


class TestValidation:
    @pytest.mark.parametrize("amount", ["0", "0.00", "-5.00", "10.005", "abc", "NaN", "Infinity", "99999999999999.99", ""])
    def test_invalid_amounts(self, client: TestClient, clean_database: None, amount: str) -> None:
        response = _post(client, str(uuid4()), amount=amount)

        assert response.status_code == 422, (amount, response.text)
        assert response.json()["code"] == "validation_error"

    @pytest.mark.parametrize("date_value", ["2026-02-30", "2026-13-01", "not-a-date", "1999-12-31", "2101-01-01"])
    def test_invalid_dates(self, client: TestClient, clean_database: None, date_value: str) -> None:
        assert _post(client, str(uuid4()), first_due_date=date_value).status_code == 422

    @pytest.mark.parametrize("currency", ["EU", "EURO", "12E", ""])
    def test_invalid_currency(self, client: TestClient, clean_database: None, currency: str) -> None:
        assert _post(client, str(uuid4()), currency=currency).status_code == 422

    @pytest.mark.parametrize("override", [{"name": ""}, {"name": "  "}, {"name": "x" * 101}, {"schedule": "weekly"}, {"schedule": "yearly"}, {"description": "x" * 501}])
    def test_invalid_names_schedules_and_descriptions(self, client: TestClient, clean_database: None, override: dict[str, Any]) -> None:
        assert _post(client, str(uuid4()), **override).status_code == 422

    @pytest.mark.parametrize("extra", [{"status": "archived"}, {"user_id": str(uuid4())}, {"account_id": str(uuid4())}, {"id": str(uuid4())}])
    def test_fields_the_client_must_not_set_are_rejected(self, client: TestClient, clean_database: None, extra: dict[str, Any]) -> None:
        assert _post(client, str(uuid4()), **extra).status_code == 422

    def test_a_rejected_request_stores_nothing(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _post(client, user, amount="-1")

        assert client.get(BASE, headers=auth_headers(user)).json() == []

    def test_a_malformed_id_is_a_validation_error(self, client: TestClient, clean_database: None) -> None:
        assert client.get(f"{BASE}/not-a-uuid", headers=auth_headers(str(uuid4()))).status_code == 422


class TestCurrency:
    def test_defaults_to_the_users_base_currency_without_creating_settings(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())

        created = _create(client, user)

        assert created["currency"] == "EUR"
        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user}).scalar_one() == 0

    def test_defaults_to_a_non_default_base_currency(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        with SessionLocal() as session:
            session.add(UserFinancialSettingsModel(user_id=user, base_currency="USD"))
            session.commit()

        assert _create(client, user)["currency"] == "USD"

    def test_an_explicit_currency_is_stored_as_given_and_never_converted(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())

        created = _create(client, user, currency="usd", amount="75.25")

        assert (created["currency"], created["amount"]) == ("USD", "75.25")

    def test_currencies_stay_separate_and_the_base_total_flags_what_it_leaves_out(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="Eur", amount="100.00", first_due_date="2026-11-20")
        _create(client, user, name="Usd", amount="40.00", currency="USD", first_due_date="2026-11-21")
        _create(client, user, name="Gbp one-off", schedule="one_time", amount="7.50", currency="GBP", first_due_date="2026-12-01")

        body = _upcoming(client, user)

        assert body["base_currency"] == "EUR"
        assert body["is_base_total_complete"] is False and body["excluded_currencies"] == ["GBP", "USD"]
        assert body["months"][0]["base_currency_total"] == "100.00"
        assert [(t["currency"], t["total"], t["occurrence_count"]) for t in body["months"][0]["totals_by_currency"]] == [("EUR", "100.00", 1), ("USD", "40.00", 1)]
        assert body["months"][1]["base_currency_total"] == "100.00"
        assert [(t["currency"], t["total"]) for t in body["totals_by_currency"]] == [("EUR", "1200.00"), ("GBP", "7.50"), ("USD", "480.00")]


class TestListAndDetail:
    def test_the_list_orders_active_by_next_due_date_then_ended_then_archived(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        later = _create(client, user, name="Later", first_due_date="2027-03-01")
        sooner = _create(client, user, name="Sooner", first_due_date="2026-11-18")
        ended = _create(client, user, name="Ended", first_due_date="2025-01-01", final_due_date="2025-06-01")
        archived = _create(client, user, name="Archived", first_due_date="2026-11-17")
        assert _patch(client, user, archived["id"], status="archived").status_code == 200

        listed = client.get(BASE, headers=auth_headers(user)).json()

        assert [item["name"] for item in listed] == ["Sooner", "Later", "Ended", "Archived"]
        assert [item["next_due_date"] for item in listed] == ["2026-11-18", "2027-03-01", None, None]
        assert {sooner["id"], later["id"], ended["id"], archived["id"]} == {item["id"] for item in listed}

    def test_detail_returns_the_obligation(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)

        assert client.get(f"{BASE}/{created['id']}", headers=auth_headers(user)).json() == created

    def test_detail_of_a_missing_obligation_is_a_stable_404(self, client: TestClient, clean_database: None) -> None:
        response = client.get(f"{BASE}/{uuid4()}", headers=auth_headers(str(uuid4())))

        assert response.status_code == 404
        assert response.json() == {"detail": "Future obligation not found.", "code": "future_obligation_not_found"}


class TestUpdateAndArchive:
    def test_update_changes_the_fields_and_the_next_projection(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, amount="100.00", first_due_date="2026-11-20")
        before = _upcoming(client, user)

        response = _patch(client, user, created["id"], name="Renamed", amount="130.50", description="New note", first_due_date="2026-11-25")
        after = _upcoming(client, user)

        assert response.status_code == 200, response.text
        assert (response.json()["name"], response.json()["amount"], response.json()["description"]) == ("Renamed", "130.50", "New note")
        assert before["months"][0]["occurrences"][0]["due_date"] == "2026-11-20"
        assert after["months"][0]["occurrences"][0]["due_date"] == "2026-11-25"
        assert _totals(before)[0] == "100.00" and _totals(after)[0] == "130.50"
        assert response.json()["updated_at"] >= created["updated_at"]

    def test_archive_removes_every_occurrence_immediately_but_keeps_the_record(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, amount="100.00")
        assert _totals(_upcoming(client, user))[0] == "100.00"

        archived = _patch(client, user, created["id"], status="archived")

        assert archived.status_code == 200 and archived.json()["status"] == "archived"
        assert archived.json()["next_due_date"] is None
        assert sum(m["occurrence_count"] for m in _upcoming(client, user)["months"]) == 0
        assert client.get(f"{BASE}/{created['id']}", headers=auth_headers(user)).json()["status"] == "archived"

    def test_restoring_brings_the_occurrences_back(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)
        _patch(client, user, created["id"], status="archived")

        restored = _patch(client, user, created["id"], status="active")

        assert restored.json()["status"] == "active" and restored.json()["next_due_date"] == "2026-11-20"
        assert sum(m["occurrence_count"] for m in _upcoming(client, user)["months"]) == 12

    def test_an_archived_obligation_can_still_be_edited(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)
        _patch(client, user, created["id"], status="archived")

        response = _patch(client, user, created["id"], amount="55.00")

        assert response.status_code == 200 and response.json()["amount"] == "55.00" and response.json()["status"] == "archived"

    def test_the_final_due_date_and_description_can_be_cleared(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user, description="Note", final_due_date="2027-01-20")

        response = _patch(client, user, created["id"], description=None, final_due_date=None)

        assert response.status_code == 200
        assert (response.json()["description"], response.json()["final_due_date"]) == (None, None)

    def test_the_resulting_schedule_is_validated_against_the_stored_values(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        monthly = _create(client, user, first_due_date="2026-12-10", final_due_date="2027-03-10")
        one_time = _create(client, user, name="One", schedule="one_time", first_due_date="2026-12-10")

        before_first = _patch(client, user, monthly["id"], first_due_date="2027-06-01")  # now after the stored final date
        final_on_one_time = _patch(client, user, one_time["id"], final_due_date="2027-01-01")

        for response in (before_first, final_on_one_time):
            assert response.status_code == 422
            assert response.json()["code"] == "future_obligation_schedule_invalid"
        assert client.get(f"{BASE}/{monthly['id']}", headers=auth_headers(user)).json()["first_due_date"] == "2026-12-10"

    def test_the_schedule_kind_cannot_be_changed(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)

        assert _patch(client, user, created["id"], schedule="one_time").status_code == 422

    @pytest.mark.parametrize("fields", [{}, {"amount": "0"}, {"amount": "1.234"}, {"name": ""}, {"status": "paused"}, {"currency": "EU"}, {"first_due_date": None}])
    def test_invalid_updates_are_rejected_and_change_nothing(self, client: TestClient, clean_database: None, fields: dict[str, Any]) -> None:
        user = str(uuid4())
        created = _create(client, user)

        assert _patch(client, user, created["id"], **fields).status_code == 422
        assert client.get(f"{BASE}/{created['id']}", headers=auth_headers(user)).json() == created

    def test_updating_a_missing_obligation_is_404(self, client: TestClient, clean_database: None) -> None:
        response = _patch(client, str(uuid4()), str(uuid4()), name="x")

        assert response.status_code == 404 and response.json()["code"] == "future_obligation_not_found"

    def test_there_is_no_delete(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)

        assert client.delete(f"{BASE}/{created['id']}", headers=auth_headers(user)).status_code == 405


class TestProjectionBounds:
    def test_exactly_twelve_calendar_months_including_the_current_one(self, client: TestClient, clean_database: None) -> None:
        body = _upcoming(client, str(uuid4()))

        assert body["as_of"] == "2026-11-16" and body["horizon_months"] == 12 and len(body["months"]) == 12
        assert (body["window_start"], body["window_end"]) == ("2026-11-01", "2027-10-31")
        assert (body["months"][0]["period_start"], body["months"][0]["period_end"]) == ("2026-11-01", "2026-11-30")
        assert body["months"][11]["period_end"] == "2027-10-31"

    def test_a_due_date_in_the_thirteenth_month_is_outside_the_window(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="Inside", schedule="one_time", first_due_date="2027-10-31")
        _create(client, user, name="Outside", schedule="one_time", first_due_date="2027-11-01")

        body = _upcoming(client, user)

        assert [o["name"] for m in body["months"] for o in m["occurrences"]] == ["Inside"]

    def test_the_current_month_excludes_earlier_days_and_includes_the_rest(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="Past", schedule="one_time", first_due_date="2026-11-15")
        _create(client, user, name="Today", schedule="one_time", first_due_date="2026-11-16")
        _create(client, user, name="Month end", schedule="one_time", first_due_date="2026-11-30")

        assert [o["name"] for o in _upcoming(client, user)["months"][0]["occurrences"]] == ["Today", "Month end"]

    def test_an_empty_projection(self, client: TestClient, clean_database: None) -> None:
        body = _upcoming(client, str(uuid4()))

        assert set(_totals(body)) == {"0.00"} and body["is_base_total_complete"] is True
        assert body["excluded_currencies"] == [] and body["totals_by_currency"] == []

    def test_occurrences_are_itemized_and_ordered(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        b = _create(client, user, name="Beta", first_due_date="2026-11-25")
        a = _create(client, user, name="Alpha", first_due_date="2026-11-25", amount="0.10")
        z = _create(client, user, name="Zeta", first_due_date="2026-11-18", amount="0.20")

        month = _upcoming(client, user)["months"][0]

        assert [o["name"] for o in month["occurrences"]] == ["Zeta", "Alpha", "Beta"]
        assert [o["obligation_id"] for o in month["occurrences"]] == [z["id"], a["id"], b["id"]]
        assert month["occurrence_count"] == 3 and month["base_currency_total"] == "120.30"

    def test_decimal_arithmetic_is_exact(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, name="A", amount="0.10")
        _create(client, user, name="B", amount="0.20")
        _create(client, user, name="C", amount="9999999999.99")

        body = _upcoming(client, user)

        assert body["months"][0]["base_currency_total"] == "10000000000.29"
        assert body["base_currency_window_total"] == "120000000003.48"


class TestAuthenticationAndIsolation:
    def test_every_route_requires_authentication(self, client: TestClient, clean_database: None) -> None:
        some_id = uuid4()

        assert client.post(BASE, json=_body()).status_code == 401
        assert client.get(BASE).status_code == 401
        assert client.get(f"{BASE}/upcoming").status_code == 401
        assert client.get(f"{BASE}/{some_id}").status_code == 401
        assert client.patch(f"{BASE}/{some_id}", json={"name": "x"}).status_code == 401

    def test_another_users_obligation_looks_exactly_like_a_missing_one(self, client: TestClient, clean_database: None) -> None:
        owner, intruder = str(uuid4()), str(uuid4())
        created = _create(client, owner, name="Private rent")

        foreign_get = client.get(f"{BASE}/{created['id']}", headers=auth_headers(intruder))
        foreign_patch = _patch(client, intruder, created["id"], status="archived")
        missing = client.get(f"{BASE}/{uuid4()}", headers=auth_headers(intruder))

        assert foreign_get.status_code == foreign_patch.status_code == missing.status_code == 404
        assert foreign_get.json() == foreign_patch.json() == missing.json()
        assert "Private rent" not in foreign_get.text + foreign_patch.text
        assert client.get(f"{BASE}/{created['id']}", headers=auth_headers(owner)).json()["status"] == "active"

    def test_lists_and_projections_never_include_another_users_data(self, client: TestClient, clean_database: None) -> None:
        owner, other = str(uuid4()), str(uuid4())
        _create(client, owner, name="Mine", amount="10.00")
        _create(client, other, name="Theirs", amount="9999.00", currency="USD")

        listing = client.get(BASE, headers=auth_headers(owner)).json()
        body = _upcoming(client, owner)

        assert [item["name"] for item in listing] == ["Mine"]
        assert [o["name"] for m in body["months"] for o in m["occurrences"]] == ["Mine"] * 12
        assert body["excluded_currencies"] == [] and body["is_base_total_complete"] is True

    def test_the_user_id_comes_from_authentication_not_the_body(self, client: TestClient, clean_database: None) -> None:
        owner, other = str(uuid4()), str(uuid4())

        response = client.post(BASE, headers=auth_headers(owner), json=_body(user_id=other))

        assert response.status_code == 422
        assert client.get(BASE, headers=auth_headers(other)).json() == []

    def test_the_static_upcoming_path_is_not_captured_as_an_id(self, client: TestClient, clean_database: None) -> None:
        assert client.get(f"{BASE}/upcoming", headers=auth_headers(str(uuid4()))).status_code == 200


class TestNoSideEffectsOnOtherDomains:
    def _snapshot(self) -> list[Any]:
        with SessionLocal() as session:
            return [
                session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in ("expenses", "income", "account_transactions", "account_transfers", "goal_transactions", "financial_events", "rule_executions", "budgets", "categories")
            ] + [
                session.execute(text("SELECT id::text, name, currency, updated_at::text FROM accounts ORDER BY id")).all(),
                session.execute(text("SELECT id::text, status, priority_rank, updated_at::text FROM goals ORDER BY id")).all(),
            ]

    def test_recording_editing_and_archiving_creates_no_expense_transaction_event_or_reservation(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        account = create_account(client, user, opening_balance="800.00")
        goal = client.post("/api/v1/goals", headers=auth_headers(user), json={"name": "Trip", "target_amount": "1000.00", "currency": "EUR", "target_date": "2027-06-30", "status": "active"}).json()
        create_goal_transaction(client, user, goal["id"], amount=100)
        linked = client.post(
            f"/api/v1/goals/{goal['id']}/transactions",
            headers=auth_headers(user),
            json={"type": "contribution", "amount": "200.00", "account_id": account["id"], "client_request_id": str(uuid4())},
        )
        assert linked.status_code == 201, linked.text

        accounts_before = client.get("/api/v1/accounts", headers=auth_headers(user)).json()
        goals_before = client.get("/api/v1/goals", headers=auth_headers(user)).json()
        rows_before = self._snapshot()

        monthly = _create(client, user, name="Rent", amount="950.00")
        _create(client, user, name="Tax", schedule="one_time", amount="300.00", first_due_date="2026-12-31")
        assert _patch(client, user, monthly["id"], amount="990.00").status_code == 200
        assert _patch(client, user, monthly["id"], status="archived").status_code == 200
        assert _upcoming(client, user)["months"]

        assert client.get("/api/v1/accounts", headers=auth_headers(user)).json() == accounts_before
        assert client.get("/api/v1/goals", headers=auth_headers(user)).json() == goals_before
        assert self._snapshot() == rows_before
        assert client.get("/api/v1/expenses", headers=auth_headers(user)).json() == []

    def test_a_past_due_date_is_never_turned_into_an_expense(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user, first_due_date="2026-01-01")

        assert client.get("/api/v1/expenses", headers=auth_headers(user)).json() == []

    def test_the_savings_overview_and_history_comparison_are_unchanged(self, client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.goals import goal_service

        class FrozenGoalDate(date):
            @classmethod
            def today(cls) -> "FrozenGoalDate":
                return cls(TODAY.year, TODAY.month, TODAY.day)

        monkeypatch.setattr(goal_service, "date", FrozenGoalDate)
        user = str(uuid4())
        client.post("/api/v1/goals", headers=auth_headers(user), json={"name": "Laptop", "target_amount": "600.00", "currency": "EUR", "target_date": "2026-12-20", "status": "active"})
        before = client.get("/api/v1/goals/savings-overview", headers=auth_headers(user)).json()

        _create(client, user, name="Rent", amount="950.00")
        _create(client, user, name="Tax", schedule="one_time", amount="300.00", first_due_date="2026-12-01")

        assert client.get("/api/v1/goals/savings-overview", headers=auth_headers(user)).json() == before


class TestCreateIdempotency:
    def test_a_replay_returns_the_original_and_creates_nothing(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())

        first = _post(client, user, client_request_id=key)
        second = _post(client, user, client_request_id=key)

        assert (first.status_code, second.status_code) == (201, 200)
        assert first.json()["id"] == second.json()["id"] and second.json()["client_request_id"] == key
        assert len(client.get(BASE, headers=auth_headers(user)).json()) == 1

    def test_the_same_key_with_a_different_request_is_a_conflict(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        _post(client, user, client_request_id=key)

        for override in ({"amount": "121.00"}, {"name": "Other"}, {"schedule": "one_time"}, {"first_due_date": "2026-11-21"}, {"final_due_date": "2027-01-20"}, {"currency": "USD"}, {"description": "x"}):
            response = _post(client, user, client_request_id=key, **override)

            assert response.status_code == 409, (override, response.text)
            assert response.json() == {
                "detail": "client_request_id has already been used for a different future obligation.",
                "code": "future_obligation_idempotency_conflict",
            }
        assert len(client.get(BASE, headers=auth_headers(user)).json()) == 1

    def test_equivalent_spellings_are_the_same_request(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        first = _post(client, user, client_request_id=key, amount="120", currency="eur", name=" Car insurance ")

        replay = _post(client, user, client_request_id=key, amount="120.00", currency="EUR", name="Car insurance")

        assert (first.status_code, replay.status_code) == (201, 200)

    def test_an_omitted_currency_and_the_base_currency_written_out_are_the_same_request(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        first = _post(client, user, client_request_id=key)

        replay = _post(client, user, client_request_id=key, currency="EUR")

        assert (first.status_code, replay.status_code) == (201, 200)

    def test_a_replay_after_an_edit_returns_the_current_state_not_a_conflict(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        created = _post(client, user, client_request_id=key).json()
        _patch(client, user, created["id"], amount="200.00", status="archived")

        replay = _post(client, user, client_request_id=key)

        assert replay.status_code == 200
        assert (replay.json()["amount"], replay.json()["status"]) == ("200.00", "archived")

    def test_keys_are_per_user(self, client: TestClient, clean_database: None) -> None:
        key = str(uuid4())

        first = _post(client, str(uuid4()), client_request_id=key)
        second = _post(client, str(uuid4()), client_request_id=key)

        assert (first.status_code, second.status_code) == (201, 201) and first.json()["id"] != second.json()["id"]

    def test_without_a_key_every_request_creates_a_record(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())

        _post(client, user)
        _post(client, user)

        assert len(client.get(BASE, headers=auth_headers(user)).json()) == 2

    def test_a_malformed_key_is_rejected(self, client: TestClient, clean_database: None) -> None:
        assert _post(client, str(uuid4()), client_request_id="not-a-uuid").status_code == 422

    def test_a_replay_does_not_count_against_the_active_limit(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        _post(client, user, client_request_id=key)
        _fill_to_limit(user, future_obligation_service.MAX_ACTIVE_OBLIGATIONS - 1)

        assert _post(client, user, client_request_id=key).status_code == 200

    def test_concurrent_duplicate_submissions_create_exactly_one_record(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        body = _body(client_request_id=key)
        barrier = Barrier(8)

        def post() -> Any:
            with TestClient(app) as thread_client:
                barrier.wait(timeout=15)
                return thread_client.post(BASE, headers=auth_headers(user), json=body)

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = [future.result(timeout=60) for future in [pool.submit(post) for _ in range(8)]]

        assert sorted(r.status_code for r in responses) == [200] * 7 + [201], [r.text for r in responses]
        assert len({r.json()["id"] for r in responses}) == 1
        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM future_obligations WHERE user_id = :u"), {"u": user}).scalar_one() == 1

    def test_concurrent_requests_with_different_bodies_and_one_key_create_one_record(self, client: TestClient, clean_database: None) -> None:
        user, key = str(uuid4()), str(uuid4())
        barrier = Barrier(4)

        def post(amount: str) -> Any:
            with TestClient(app) as thread_client:
                barrier.wait(timeout=15)
                return thread_client.post(BASE, headers=auth_headers(user), json=_body(client_request_id=key, amount=amount))

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = [f.result(timeout=60) for f in [pool.submit(post, a) for a in ("1.00", "2.00", "3.00", "4.00")]]

        assert sorted(r.status_code for r in responses) == [201, 409, 409, 409], [r.text for r in responses]


def _fill_to_limit(user: str, count: int) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO future_obligations (id, user_id, name, schedule, amount, currency, first_due_date, status) "
                "SELECT gen_random_uuid(), :u, 'Bill ' || g, 'monthly', 10.00, 'EUR', DATE '2026-12-01', 'active' FROM generate_series(1, :n) AS g"
            ),
            {"u": user, "n": count},
        )
        session.commit()


class TestActiveLimit:
    def test_the_201st_active_obligation_is_refused_with_a_stable_error(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _fill_to_limit(user, future_obligation_service.MAX_ACTIVE_OBLIGATIONS)

        response = _post(client, user)

        assert response.status_code == 409
        assert response.json()["code"] == "future_obligation_limit_reached"
        assert len(client.get(BASE, headers=auth_headers(user)).json()) == future_obligation_service.MAX_ACTIVE_OBLIGATIONS

    def test_archiving_one_makes_room_and_restoring_at_the_limit_is_refused(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _fill_to_limit(user, future_obligation_service.MAX_ACTIVE_OBLIGATIONS - 1)
        last = _create(client, user, name="Last")
        assert _post(client, user).status_code == 409

        assert _patch(client, user, last["id"], status="archived").status_code == 200
        replacement = _post(client, user, name="Replacement")
        restore = _patch(client, user, last["id"], status="active")

        assert replacement.status_code == 201
        assert restore.status_code == 409 and restore.json()["code"] == "future_obligation_limit_reached"

    def test_archived_obligations_do_not_count_and_other_users_are_unaffected(self, client: TestClient, clean_database: None) -> None:
        full, other = str(uuid4()), str(uuid4())
        _fill_to_limit(full, future_obligation_service.MAX_ACTIVE_OBLIGATIONS)

        assert _post(client, other).status_code == 201

    def test_editing_an_active_obligation_at_the_limit_is_allowed(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _fill_to_limit(user, future_obligation_service.MAX_ACTIVE_OBLIGATIONS - 1)
        last = _create(client, user)

        assert _patch(client, user, last["id"], amount="11.00").status_code == 200

    def test_the_projection_stays_bounded_at_the_limit(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _fill_to_limit(user, future_obligation_service.MAX_ACTIVE_OBLIGATIONS)

        body = _upcoming(client, user)

        assert len(body["months"]) == 12
        # The seeded bills first fall due on 2026-12-01, so November has none.
        assert body["months"][0]["occurrence_count"] == 0
        assert body["months"][1]["occurrence_count"] == future_obligation_service.MAX_ACTIVE_OBLIGATIONS
        assert body["months"][1]["base_currency_total"] == "2000.00"


class TestReadOnlyAndQueryCount:
    def test_the_projection_executes_no_write_and_creates_no_settings_row(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get(f"{BASE}/upcoming", headers=auth_headers(user))
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200
        assert statements
        for statement in statements:
            assert statement.startswith("SELECT"), statement
            assert "FOR UPDATE" not in statement and "FOR SHARE" not in statement, statement
        with SessionLocal() as session:
            assert session.execute(text("SELECT count(*) FROM user_financial_settings WHERE user_id = :u"), {"u": user}).scalar_one() == 0

    def test_listing_and_detail_execute_no_write(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        created = _create(client, user)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", record)
        try:
            client.get(BASE, headers=auth_headers(user))
            client.get(f"{BASE}/{created['id']}", headers=auth_headers(user))
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert statements and all(s.startswith("SELECT") for s in statements)

    def test_the_stored_data_is_identical_before_and_after_a_projection(self, client: TestClient, clean_database: None) -> None:
        user = str(uuid4())
        _create(client, user)

        def snapshot() -> Any:
            with SessionLocal() as session:
                return session.execute(text("SELECT id::text, amount::text, status, updated_at::text FROM future_obligations ORDER BY id")).all()

        before = snapshot()

        for _ in range(2):
            _upcoming(client, user)

        assert snapshot() == before

    def test_the_number_of_queries_does_not_grow_with_the_number_of_obligations(self, client: TestClient, clean_database: None) -> None:
        def count_statements(user: str) -> int:
            statements: list[str] = []

            def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                assert client.get(f"{BASE}/upcoming", headers=auth_headers(user)).status_code == 200
                assert client.get(BASE, headers=auth_headers(user)).status_code == 200
            finally:
                event.remove(engine, "before_cursor_execute", record)

            return len(statements)

        few, many = str(uuid4()), str(uuid4())
        _create(client, few)
        _fill_to_limit(many, 60)

        assert count_statements(many) == count_statements(few)
