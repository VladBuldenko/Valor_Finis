import inspect
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.database_base import Base
from app.db.database_models import import_database_models
from app.db.database_session import SessionLocal, engine
from app.main import app
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.financial_events import (
    financial_event_repository,
    financial_event_service,
)
from app.modules.financial_events.financial_event_models import FinancialEventModel
from app.modules.income import income_service
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate
from tests.helpers import auth_headers, create_account
from tests.schema_drift import E4_UNMAPPED_OBJECTS, exclude_stages_after, split_unmapped_e4

# VF-020E3 tests: every canonical Income mutation writes one financial_events
# outbox row in the SAME transaction. E3 only writes pending events; nothing
# here processes them. The shared valor_test database (migrated to the E2
# revision) is used through the clean_database fixture, whose
# validate_test_database_url guard runs before any destructive step.

TODAY = date(2026, 10, 20)


@pytest.fixture
def fixed_today(monkeypatch) -> date:
    monkeypatch.setattr(financial_event_service, "server_today", lambda: TODAY)
    return TODAY


@pytest.fixture
def failing_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _events(aggregate_id: Optional[str] = None, user_id: Optional[str] = None) -> List[FinancialEventModel]:
    session = SessionLocal()
    try:
        query = session.query(FinancialEventModel)
        if aggregate_id is not None:
            query = query.filter(FinancialEventModel.aggregate_id == UUID(aggregate_id))
        if user_id is not None:
            query = query.filter(FinancialEventModel.user_id == UUID(user_id))
        events = query.order_by(FinancialEventModel.occurred_at, FinancialEventModel.event_type).all()
        for event in events:
            session.expunge(event)
        return events
    finally:
        session.close()


def _events_by_type(aggregate_id: str) -> Dict[str, List[FinancialEventModel]]:
    grouped: Dict[str, List[FinancialEventModel]] = {}
    for event in _events(aggregate_id=aggregate_id):
        grouped.setdefault(event.event_type, []).append(event)
    return grouped


def _income_row(income_id: str) -> Optional[IncomeModel]:
    session = SessionLocal()
    try:
        row = session.get(IncomeModel, UUID(income_id))
        if row is not None:
            session.expunge(row)
        return row
    finally:
        session.close()


def _scalar(sql: str, **params: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def _post_income(
    client: TestClient, user_id: str, received_at: date, amount: str = "100.00",
    account_id: Optional[str] = None, currency: str = "EUR", source: str = "salary",
):
    payload: Dict[str, Any] = {
        "amount": amount, "currency": currency, "received_at": received_at.isoformat(),
        "source": source, "description": None,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    return client.post("/api/v1/income", headers=auth_headers(user_id), json=payload)


def _patch_income(client: TestClient, user_id: str, income_id: str, **fields: Any):
    return client.patch(f"/api/v1/income/{income_id}", headers=auth_headers(user_id), json=fields)


def _legacy_income(user_id: str, received_at: date = date(2026, 1, 5)) -> str:
    """An Income created before E3: a canonical row with no event at all."""
    session = SessionLocal()
    try:
        income = IncomeModel(
            user_id=UUID(user_id), amount=Decimal("300.00"), currency="EUR",
            received_at=received_at, source="gift", description=None,
            base_amount=Decimal("300.00"), base_currency="EUR", fx_rate=Decimal("1"),
            fx_rate_date=received_at, fx_source="identity",
        )
        session.add(income)
        session.commit()
        return str(income.id)
    finally:
        session.close()


# ------------------------------------------------------------------
# A. ORM / repository
# ------------------------------------------------------------------


def test_model_maps_exactly_the_e2_table_without_schema_drift() -> None:
    import_database_models()
    assert "financial_events" in Base.metadata.tables

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    # The database may be at a later stage than E2; only objects introduced by
    # stages AFTER its own revision, and the E4 rules tables that stay
    # unmapped until E5, are expected differences.
    differences = exclude_stages_after(differences, revision)
    if revision == "861064d31463":
        expected_unmapped, differences = split_unmapped_e4(differences)
        assert {d[1].name for d in expected_unmapped if d[0] == "remove_table"} == set(E4_UNMAPPED_OBJECTS)

    assert differences == []


def test_model_has_no_foreign_keys_and_no_income_relationship() -> None:
    table = FinancialEventModel.__table__
    assert not table.foreign_keys
    assert not sa_inspect(FinancialEventModel).relationships
    assert "financial_events" not in {
        column.table.name for column in IncomeModel.__table__.columns
    }
    assert "origin" not in IncomeModel.__table__.columns
    assert "ingestion_mode" not in IncomeModel.__table__.columns


def test_repository_write_primitive_has_no_commit_parameter() -> None:
    parameters = inspect.signature(financial_event_repository.create_event).parameters
    assert "commit" not in parameters

    source = inspect.getsource(financial_event_repository)
    assert ".commit(" not in source and ".rollback(" not in source


def test_event_insert_flushes_but_never_commits_independently(clean_database: None) -> None:
    session = SessionLocal()
    user_id = uuid4()
    try:
        event = financial_event_repository.create_event(
            db_session=session, user_id=user_id, event_type="income.created",
            aggregate_type="income", aggregate_id=uuid4(), origin="manual",
            ingestion_mode="live", snap_amount=Decimal("10.00"), snap_currency="EUR",
            snap_received_at=TODAY, snap_account_id=None, snap_income_source="salary",
            snap_aggregate_updated_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
            not_before=datetime(2026, 10, 20, tzinfo=timezone.utc),
        )

        # Flushed (visible inside the transaction, defaults loaded) ...
        assert event.status == "pending" and event.attempts == 0
        assert event.occurred_at is not None
        assert session.query(FinancialEventModel).filter_by(user_id=user_id).count() == 1
        # ... but not committed: another connection sees nothing.
        assert _scalar("SELECT count(*) FROM financial_events WHERE user_id = :u", u=user_id) == 0

        session.rollback()
        assert session.query(FinancialEventModel).filter_by(user_id=user_id).count() == 0
    finally:
        session.close()


# ------------------------------------------------------------------
# provenance and not_before helpers
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "received_at, expected",
    [
        (date(2026, 10, 20), "live"),
        (date(2026, 10, 14), "live"),
        (date(2026, 10, 13), "live"),        # exactly creation date - 7 days: inclusive
        (date(2026, 10, 12), "historical"),  # one day older than the boundary
        (date(2026, 1, 1), "historical"),
        (date(2026, 10, 21), "live"),        # future dates are live (deferred by not_before)
    ],
)
def test_manual_creation_classification_boundary(received_at: date, expected: str) -> None:
    assert financial_event_service.classify_manual_creation(received_at, TODAY) == expected


def test_not_before_is_utc_midnight_of_a_future_received_at_day() -> None:
    value = financial_event_service.compute_not_before(date(2026, 10, 25), TODAY)
    assert value == datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)


def test_not_before_is_database_now_for_current_and_past_dates() -> None:
    for received_at in (TODAY, date(2026, 9, 1)):
        value = financial_event_service.compute_not_before(received_at, TODAY)
        assert not isinstance(value, datetime)


# ------------------------------------------------------------------
# B. unlinked create
# ------------------------------------------------------------------


def test_unlinked_create_writes_income_and_one_created_event(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())

    response = _post_income(client, user_id, received_at=date(2026, 10, 15), amount="2500.50", source="freelance")

    assert response.status_code == 201, response.text
    body = response.json()
    events = _events(aggregate_id=body["id"])
    assert len(events) == 1
    event = events[0]
    assert (event.event_type, event.aggregate_type) == ("income.created", "income")
    assert str(event.aggregate_id) == body["id"] and str(event.user_id) == user_id
    assert (event.origin, event.ingestion_mode) == ("manual", "live")
    assert event.snap_amount == Decimal("2500.50") and event.snap_currency == "EUR"
    assert event.snap_received_at == date(2026, 10, 15) and event.snap_income_source == "freelance"
    assert event.snap_account_id is None
    assert (event.status, event.attempts) == ("pending", 0)
    assert event.next_attempt_at is None and event.lease_expires_at is None
    assert event.claim_token is None and event.processed_at is None and event.outcome_summary is None
    # The persisted Income.updated_at is the snapshot's updated_at.
    assert event.snap_aggregate_updated_at == _income_row(body["id"]).updated_at
    assert event.not_before == event.occurred_at  # both are the transaction's now()


def test_snapshot_amount_is_original_amount_not_base_amount(
    client: TestClient, clean_database: None, fixed_today: date, monkeypatch,
) -> None:
    from unittest.mock import MagicMock
    from app.modules.fx import fx_ecb_provider

    payload = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.25, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-10-19"}]}]}},
    }
    http_response = MagicMock(status_code=200)
    http_response.json.return_value = payload
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=http_response))
    user_id = str(uuid4())

    response = _post_income(client, user_id, received_at=date(2026, 10, 19), amount="100.00", currency="USD")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["base_amount"] != body["amount"]
    event = _events(aggregate_id=body["id"])[0]
    assert event.snap_amount == Decimal("100.00") and event.snap_currency == "USD"


# ------------------------------------------------------------------
# C. linked create
# ------------------------------------------------------------------


def test_linked_create_writes_income_projection_and_event_with_account(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")

    response = _post_income(client, user_id, received_at=TODAY, amount="750.00", account_id=account["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_id"] == account["id"]
    event = _events(aggregate_id=body["id"])[0]
    assert event.event_type == "income.created" and str(event.snap_account_id) == account["id"]
    assert event.snap_amount == Decimal("750.00")
    projections = _scalar(
        "SELECT count(*) FROM account_transactions WHERE income_id = :i", i=UUID(body["id"]),
    )
    assert projections == 1
    balance = client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()[0]["current_balance"]
    assert Decimal(balance) == Decimal("750.00")


# ------------------------------------------------------------------
# D / E. P51 boundary and future-dated
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "received_at, expected_mode",
    [(date(2026, 10, 13), "live"), (date(2026, 10, 12), "historical")],
)
def test_created_event_mode_follows_the_seven_day_boundary_via_api(
    client: TestClient, clean_database: None, fixed_today: date, received_at: date, expected_mode: str,
) -> None:
    user_id = str(uuid4())

    body = _post_income(client, user_id, received_at=received_at).json()

    event = _events(aggregate_id=body["id"])[0]
    assert (event.origin, event.ingestion_mode) == ("manual", expected_mode)


def test_future_dated_income_event_is_deferred_to_the_start_of_its_day(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())

    response = _post_income(client, user_id, received_at=date(2026, 10, 25))

    assert response.status_code == 201, response.text
    event = _events(aggregate_id=response.json()["id"])[0]
    assert event.ingestion_mode == "live"
    assert event.not_before == datetime.combine(date(2026, 10, 25), time.min, tzinfo=timezone.utc)
    assert event.status == "pending"


def test_current_dated_income_event_is_not_deferred(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())

    body = _post_income(client, user_id, received_at=TODAY).json()

    event = _events(aggregate_id=body["id"])[0]
    assert event.not_before == event.occurred_at


# ------------------------------------------------------------------
# F. update
# ------------------------------------------------------------------


def test_update_emits_one_updated_event_with_the_final_snapshot(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    body = _post_income(client, user_id, received_at=TODAY, amount="100.00").json()

    response = _patch_income(client, user_id, body["id"], amount="175.25", source="gift", received_at="2026-10-18")

    assert response.status_code == 200, response.text
    grouped = _events_by_type(body["id"])
    assert len(grouped["income.created"]) == 1 and len(grouped["income.updated"]) == 1
    updated = grouped["income.updated"][0]
    assert (updated.origin, updated.ingestion_mode) == ("manual", "correction")
    assert updated.snap_amount == Decimal("175.25") and updated.snap_income_source == "gift"
    assert updated.snap_received_at == date(2026, 10, 18) and updated.snap_currency == "EUR"
    assert updated.snap_aggregate_updated_at == _income_row(body["id"]).updated_at
    assert updated.snap_aggregate_updated_at >= grouped["income.created"][0].snap_aggregate_updated_at
    assert (updated.status, updated.attempts) == ("pending", 0)
    # The created event still describes the ORIGINAL state.
    assert grouped["income.created"][0].snap_amount == Decimal("100.00")


def test_update_attach_move_and_detach_record_the_final_account_link(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    first = create_account(client, user_id, name="A", currency="EUR")
    second = create_account(client, user_id, name="B", currency="EUR")
    body = _post_income(client, user_id, received_at=TODAY).json()

    def last_updated_account() -> Optional[str]:
        updated = [e for e in _events(aggregate_id=body["id"]) if e.event_type == "income.updated"][-1]
        return str(updated.snap_account_id) if updated.snap_account_id else None

    assert _patch_income(client, user_id, body["id"], account_id=first["id"]).status_code == 200  # attach
    assert last_updated_account() == first["id"]
    assert _patch_income(client, user_id, body["id"], amount="55.00").status_code == 200  # stay
    assert last_updated_account() == first["id"]
    assert _patch_income(client, user_id, body["id"], account_id=second["id"]).status_code == 200  # move
    assert last_updated_account() == second["id"]
    assert _patch_income(client, user_id, body["id"], account_id=None).status_code == 200  # detach
    assert last_updated_account() is None

    updated_events = [e for e in _events(aggregate_id=body["id"]) if e.event_type == "income.updated"]
    assert len(updated_events) == 4
    assert len([e for e in _events(aggregate_id=body["id"]) if e.event_type == "income.created"]) == 1


def test_update_of_a_pre_e3_income_emits_only_an_updated_event(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    income_id = _legacy_income(user_id)
    assert _events(aggregate_id=income_id) == []  # no backfill: nothing exists yet

    assert client.get("/api/v1/income", headers=auth_headers(user_id)).status_code == 200
    assert _events(aggregate_id=income_id) == []  # reads create no event

    assert _patch_income(client, user_id, income_id, amount="310.00").status_code == 200

    events = _events(aggregate_id=income_id)
    assert [e.event_type for e in events] == ["income.updated"]
    assert (events[0].origin, events[0].ingestion_mode) == ("manual", "correction")


# ------------------------------------------------------------------
# G. delete
# ------------------------------------------------------------------


def test_delete_emits_a_deleted_event_with_the_last_state_and_event_survives(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")
    body = _post_income(client, user_id, received_at=TODAY, amount="400.00", account_id=account["id"]).json()
    assert _patch_income(client, user_id, body["id"], amount="420.00").status_code == 200
    last_updated_at = _income_row(body["id"]).updated_at

    response = client.delete(f"/api/v1/income/{body['id']}", headers=auth_headers(user_id))

    assert response.status_code == 204
    assert _income_row(body["id"]) is None
    assert _scalar("SELECT count(*) FROM account_transactions WHERE income_id = :i", i=UUID(body["id"])) == 0
    grouped = _events_by_type(body["id"])
    assert sorted(grouped) == ["income.created", "income.deleted", "income.updated"]
    deleted = grouped["income.deleted"]
    assert len(deleted) == 1
    event = deleted[0]
    assert (event.origin, event.ingestion_mode) == ("manual", "correction")
    assert event.snap_amount == Decimal("420.00") and str(event.snap_account_id) == account["id"]
    assert event.snap_aggregate_updated_at == last_updated_at
    assert (event.status, event.attempts) == ("pending", 0)
    # No compensating Account transaction or reversal exists.
    balance = client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()[0]["current_balance"]
    assert Decimal(balance) == Decimal("0.00")


def test_delete_of_a_pre_e3_income_emits_only_a_deleted_event(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    income_id = _legacy_income(user_id)

    assert client.delete(f"/api/v1/income/{income_id}", headers=auth_headers(user_id)).status_code == 204

    events = _events(aggregate_id=income_id)
    assert [e.event_type for e in events] == ["income.deleted"]
    assert events[0].snap_amount == Decimal("300.00") and events[0].snap_account_id is None


# ------------------------------------------------------------------
# H. rollback atomicity
# ------------------------------------------------------------------


def _explode(*args: Any, **kwargs: Any):
    raise RuntimeError("forced event insertion failure")


def test_unlinked_create_rolls_back_when_the_event_insert_fails(
    failing_client: TestClient, clean_database: None, fixed_today: date, monkeypatch,
) -> None:
    user_id = str(uuid4())
    monkeypatch.setattr(financial_event_repository, "create_event", _explode)

    response = _post_income(failing_client, user_id, received_at=TODAY)

    assert response.status_code == 500
    assert _scalar("SELECT count(*) FROM income WHERE user_id = :u", u=UUID(user_id)) == 0
    assert _events(user_id=user_id) == []


def test_linked_create_rolls_back_income_projection_and_event(
    failing_client: TestClient, client: TestClient, clean_database: None, fixed_today: date, monkeypatch,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")
    monkeypatch.setattr(financial_event_repository, "create_event", _explode)

    response = _post_income(failing_client, user_id, received_at=TODAY, account_id=account["id"])

    assert response.status_code == 500
    assert _scalar("SELECT count(*) FROM income WHERE user_id = :u", u=UUID(user_id)) == 0
    assert _scalar("SELECT count(*) FROM account_transactions WHERE income_id IS NOT NULL") == 0
    assert _events(user_id=user_id) == []


def test_update_rolls_back_income_projection_and_event(
    failing_client: TestClient, client: TestClient, clean_database: None, fixed_today: date, monkeypatch,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")
    body = _post_income(client, user_id, received_at=TODAY, amount="100.00").json()
    events_before = len(_events(aggregate_id=body["id"]))
    monkeypatch.setattr(financial_event_repository, "create_event", _explode)

    response = _patch_income(failing_client, user_id, body["id"], amount="999.00", account_id=account["id"])

    assert response.status_code == 500
    assert _income_row(body["id"]).amount == Decimal("100.00")
    assert _scalar("SELECT count(*) FROM account_transactions WHERE income_id = :i", i=UUID(body["id"])) == 0
    assert len(_events(aggregate_id=body["id"])) == events_before


def test_delete_rolls_back_when_the_event_insert_fails(
    failing_client: TestClient, client: TestClient, clean_database: None, fixed_today: date, monkeypatch,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")
    body = _post_income(client, user_id, received_at=TODAY, account_id=account["id"]).json()
    events_before = len(_events(aggregate_id=body["id"]))
    monkeypatch.setattr(financial_event_repository, "create_event", _explode)

    response = failing_client.delete(f"/api/v1/income/{body['id']}", headers=auth_headers(user_id))

    assert response.status_code == 500
    assert _income_row(body["id"]) is not None
    assert _scalar("SELECT count(*) FROM account_transactions WHERE income_id = :i", i=UUID(body["id"])) == 1
    assert len(_events(aggregate_id=body["id"])) == events_before


def test_failed_mutations_create_no_event(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    other_user = str(uuid4())
    account = create_account(client, other_user, currency="EUR")
    body = _post_income(client, user_id, received_at=TODAY).json()
    baseline = len(_events(user_id=user_id))

    assert _post_income(client, user_id, received_at=TODAY, amount="-5").status_code == 422
    assert _post_income(client, user_id, received_at=TODAY, account_id=account["id"]).status_code in (404, 409, 422)
    assert _post_income(client, user_id, received_at=TODAY, currency="USD", account_id=str(uuid4())).status_code >= 400
    assert _patch_income(client, user_id, str(uuid4()), amount="1.00").status_code == 404
    assert _patch_income(client, other_user, body["id"], amount="1.00").status_code == 404  # foreign Income
    assert client.delete(f"/api/v1/income/{uuid4()}", headers=auth_headers(user_id)).status_code == 404
    assert client.delete(f"/api/v1/income/{body['id']}", headers=auth_headers(other_user)).status_code == 404

    assert len(_events(user_id=user_id)) == baseline
    assert _events(user_id=other_user) == []
    assert _income_row(body["id"]) is not None


# ------------------------------------------------------------------
# I. commit=False composing path
# ------------------------------------------------------------------


def _income_create(account_id: Optional[UUID] = None) -> IncomeCreate:
    return IncomeCreate(
        amount=Decimal("55.00"), currency="EUR", received_at=TODAY, source="salary",
        description=None, account_id=account_id,
    )


def test_unlinked_commit_false_keeps_income_and_event_uncommitted(
    clean_database: None, fixed_today: date,
) -> None:
    user_id = uuid4()
    session = SessionLocal()
    try:
        response = income_service.create_income(session, _income_create(), user_id, commit=False)

        assert session.query(FinancialEventModel).filter_by(aggregate_id=response.id).count() == 1
        assert _scalar("SELECT count(*) FROM income WHERE id = :i", i=response.id) == 0
        assert _scalar("SELECT count(*) FROM financial_events WHERE aggregate_id = :i", i=response.id) == 0

        session.rollback()
        assert session.query(FinancialEventModel).filter_by(aggregate_id=response.id).count() == 0
        assert _scalar("SELECT count(*) FROM income WHERE id = :i", i=response.id) == 0
    finally:
        session.close()


def test_linked_commit_false_keeps_income_projection_and_event_uncommitted(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = uuid4()
    account = create_account(client, str(user_id), currency="EUR")
    session = SessionLocal()
    try:
        response = income_service.create_income(
            session, _income_create(account_id=UUID(account["id"])), user_id, commit=False,
        )

        assert session.query(FinancialEventModel).filter_by(aggregate_id=response.id).count() == 1
        assert session.query(AccountTransactionModel).filter_by(income_id=response.id).count() == 1
        assert _scalar("SELECT count(*) FROM financial_events WHERE aggregate_id = :i", i=response.id) == 0
        assert _scalar("SELECT count(*) FROM account_transactions WHERE income_id = :i", i=response.id) == 0

        session.commit()
        assert _scalar("SELECT count(*) FROM financial_events WHERE aggregate_id = :i", i=response.id) == 1
        assert _scalar("SELECT count(*) FROM income WHERE id = :i", i=response.id) == 1
    finally:
        session.close()


def test_commit_true_commits_income_and_event_together(
    clean_database: None, fixed_today: date,
) -> None:
    user_id = uuid4()
    session = SessionLocal()
    try:
        response = income_service.create_income(session, _income_create(), user_id)
    finally:
        session.close()

    assert _scalar("SELECT count(*) FROM income WHERE id = :i", i=response.id) == 1
    assert _scalar("SELECT count(*) FROM financial_events WHERE aggregate_id = :i", i=response.id) == 1


# ------------------------------------------------------------------
# J. regression: no response drift, no processing
# ------------------------------------------------------------------


def test_income_http_response_shape_is_unchanged(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())

    body = _post_income(client, user_id, received_at=TODAY).json()
    listed = client.get("/api/v1/income", headers=auth_headers(user_id)).json()[0]

    expected_keys = {
        "id", "user_id", "amount", "currency", "received_at", "source", "description",
        "account_id", "base_amount", "base_currency", "fx_rate", "fx_rate_date",
        "fx_source", "created_at", "updated_at",
    }
    assert set(body) == expected_keys and set(listed) == expected_keys


def test_new_events_stay_pending_and_nothing_processes_them(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id = str(uuid4())
    body = _post_income(client, user_id, received_at=TODAY).json()
    _patch_income(client, user_id, body["id"], amount="10.00")
    client.delete(f"/api/v1/income/{body['id']}", headers=auth_headers(user_id))

    events = _events(aggregate_id=body["id"])

    assert sorted(e.event_type for e in events) == ["income.created", "income.deleted", "income.updated"]
    assert all(e.status == "pending" and e.attempts == 0 for e in events)
    assert all(
        e.processed_at is None and e.claim_token is None and e.lease_expires_at is None
        and e.next_attempt_at is None and e.last_error_code is None and e.outcome_summary is None
        for e in events
    )
    # No Goal or rule side effect exists.
    assert _scalar("SELECT count(*) FROM goal_transactions") == 0


def test_event_events_are_scoped_to_the_owner(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    first, second = str(uuid4()), str(uuid4())

    _post_income(client, first, received_at=TODAY)
    _post_income(client, second, received_at=TODAY)

    assert len(_events(user_id=first)) == 1 and len(_events(user_id=second)) == 1
    assert str(_events(user_id=first)[0].user_id) == first
