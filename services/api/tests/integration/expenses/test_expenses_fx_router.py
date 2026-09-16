from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.fx import fx_ecb_provider, fx_nbu_provider
from tests.helpers import auth_headers, create_category


def _create_expense_with(
    client: TestClient,
    user_id: str,
    amount,
    currency: str,
    expense_date: str,
    category_id=None,
    title: str = "Expense",
):
    return client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "title": title,
            "amount": amount,
            "currency": currency,
            "expense_date": expense_date,
            "description": title,
            "source": "manual",
        },
    )


def _mock_ecb(monkeypatch, rate: float, actual_date: str) -> MagicMock:
    payload = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [rate, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": actual_date}]}]}},
    }
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    get_mock = MagicMock(return_value=response)
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)
    return get_mock


def _mock_nbu(monkeypatch, rate: float, exchangedate: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [
        {"r030": 978, "txt": "Євро", "rate": rate, "cc": "EUR", "exchangedate": exchangedate, "special": None},
    ]
    get_mock = MagicMock(return_value=response)
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)
    return get_mock


# Tests (A) that creating a EUR expense produces a complete identity
# snapshot with no HTTP call.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no provider HTTP call happens.
# Returns:
# - None. The test passes if the response carries a complete identity snapshot.
def test_create_expense_endpoint_eur_produces_identity_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    # Act
    response = _create_expense_with(
        client=client, user_id=user_id, amount=50, currency="EUR", expense_date="2026-05-07",
    )

    # Assert
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["base_amount"] == "50.00"
    assert body["base_currency"] == "EUR"
    assert body["fx_rate"] == "1.00000000"
    assert body["fx_rate_date"] == "2026-05-07"
    assert body["fx_source"] == "identity"
    ecb_mock.assert_not_called()


# Tests (B) that creating a USD expense produces a complete ECB-resolved
# snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if base_amount/fx_rate reflect the mocked ECB response.
def test_create_expense_endpoint_usd_produces_ecb_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")

    # Act
    response = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    )

    # Assert
    assert response.status_code == 201, response.text
    body = response.json()
    # fx_rate is NUMERIC(18,8) - the DB rounds the full-precision computed
    # rate to 8dp on storage, so the response reflects that stored
    # precision, not the raw in-memory value.
    full_precision_rate = Decimal("1") / Decimal("1.1539")
    expected_rate = full_precision_rate.quantize(Decimal("0.00000001"))
    assert Decimal(body["fx_rate"]) == expected_rate
    assert Decimal(body["base_amount"]) == (Decimal("100") * full_precision_rate).quantize(Decimal("0.01"))
    assert body["base_currency"] == "EUR"
    assert body["fx_rate_date"] == "2026-05-07"
    assert body["fx_source"] == "ecb"


# Tests (C) that creating a UAH expense produces a complete NBU-resolved
# snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the NBU HTTP boundary.
# Returns:
# - None. The test passes if base_amount/fx_rate reflect the mocked NBU response.
def test_create_expense_endpoint_uah_produces_nbu_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    _mock_nbu(monkeypatch, rate=51.5231, exchangedate="07.05.2026")

    # Act
    response = _create_expense_with(
        client=client, user_id=user_id, amount=1000, currency="UAH", expense_date="2026-05-07",
    )

    # Assert
    assert response.status_code == 201, response.text
    body = response.json()
    # fx_rate is NUMERIC(18,8) - see the USD test above for why the
    # response is compared against the 8dp-rounded value while
    # base_amount uses the full-precision in-memory rate.
    full_precision_rate = Decimal("1") / Decimal("51.5231")
    expected_rate = full_precision_rate.quantize(Decimal("0.00000001"))
    assert Decimal(body["fx_rate"]) == expected_rate
    assert Decimal(body["base_amount"]) == (Decimal("1000") * full_precision_rate).quantize(Decimal("0.01"))
    assert body["fx_source"] == "nbu"


# Tests (D) that a provider failure results in no Expense row being
# created at all.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary as failing.
# Returns:
# - None. The test passes if the API returns an error and no expense
#   appears in a subsequent list call.
def test_create_expense_endpoint_provider_failure_creates_no_expense(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    response_mock = MagicMock()
    response_mock.status_code = 404
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=response_mock))

    # Act
    response = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    )

    # Assert
    assert response.status_code == 422
    list_response = client.get("/api/v1/expenses", headers=auth_headers(user_id))
    assert list_response.json() == []


# Tests (E) that all five snapshot fields are persisted together (not
# partially) for a successful foreign-currency creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if none of the five fields is null.
def test_create_expense_endpoint_persists_full_snapshot_atomically(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")

    # Act
    response = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    )

    # Assert
    body = response.json()
    for field in ("base_amount", "base_currency", "fx_rate", "fx_rate_date", "fx_source"):
        assert body[field] is not None, field


# Tests (F) that PATCHing only amount keeps the stored rate metadata and
# only recalculates base_amount.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if fx_rate/fx_rate_date/fx_source are unchanged
#   and base_amount reflects the new amount.
def test_update_expense_endpoint_amount_only_reuses_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")
    created = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    ).json()
    ecb_mock.reset_mock()

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"amount": 200},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fx_rate"] == created["fx_rate"]
    assert body["fx_rate_date"] == created["fx_rate_date"]
    assert body["fx_source"] == created["fx_source"]
    assert Decimal(body["base_amount"]) == (Decimal("200") * Decimal(created["fx_rate"])).quantize(Decimal("0.01"))
    ecb_mock.assert_not_called()


# Tests (G) that PATCHing currency resolves a brand new snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if fx_source/fx_rate reflect the new currency's
#   resolution.
def test_update_expense_endpoint_currency_change_gets_new_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")
    created = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    ).json()

    _mock_nbu(monkeypatch, rate=51.5231, exchangedate="07.05.2026")

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"currency": "UAH"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"] == "UAH"
    assert body["fx_source"] == "nbu"
    assert body["fx_rate"] != created["fx_rate"]


# Tests (H) that a metadata-only PATCH never calls the FX provider.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the snapshot is unchanged and no HTTP call
#   is attempted.
def test_update_expense_endpoint_metadata_only_does_not_call_provider(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    ecb_mock = _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")
    created = _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    ).json()
    ecb_mock.reset_mock()

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"title": "Renamed"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fx_rate"] == created["fx_rate"]
    assert body["base_amount"] == created["base_amount"]
    ecb_mock.assert_not_called()


# Tests (I) that a legacy unresolved expense (simulating one created
# before VF-014B5C) becomes resolved once it receives a monetary update.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the previously-null snapshot is fully
#   populated after the update.
def test_update_expense_endpoint_legacy_unresolved_monetary_update_resolves(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange - seed a legacy unresolved row directly (bypassing FX
    # resolution, simulating pre-VF-014B5C data).
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=None,
        title="Legacy USD",
        amount=Decimal("100.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    legacy_id = legacy_expense.id
    db_session.close()

    user_id = str(user_id_uuid)
    _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")

    # Act
    response = client.patch(
        f"/api/v1/expenses/{legacy_id}",
        json={"amount": 150},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fx_source"] == "ecb"
    assert body["base_amount"] is not None


# Tests (J) that a legacy unresolved expense receiving only a metadata
# update remains fully unresolved (all null).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no provider HTTP call happens.
# Returns:
# - None. The test passes if all five snapshot fields remain null.
def test_update_expense_endpoint_legacy_unresolved_metadata_update_stays_unresolved(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    from app.db.database_session import SessionLocal
    from app.modules.expenses.expenses_models import ExpenseModel

    user_id_uuid = uuid4()
    db_session = SessionLocal()
    legacy_expense = ExpenseModel(
        user_id=user_id_uuid,
        category_id=None,
        title="Legacy USD",
        amount=Decimal("100.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        source="manual",
    )
    db_session.add(legacy_expense)
    db_session.commit()
    legacy_id = legacy_expense.id
    db_session.close()

    user_id = str(user_id_uuid)
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    # Act
    response = client.patch(
        f"/api/v1/expenses/{legacy_id}",
        json={"title": "Renamed legacy"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_amount"] is None
    assert body["fx_rate"] is None
    assert body["fx_source"] is None
    ecb_mock.assert_not_called()


# Tests (L) that a client cannot inject base_amount/base_currency/fx_rate/
# fx_rate_date/fx_source on create.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the request is rejected (extra="forbid").
def test_create_expense_endpoint_rejects_injected_fx_fields(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": None,
            "title": "Hacked",
            "amount": 10,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": None,
            "source": "manual",
            "base_amount": "999999.00",
            "fx_rate": "1.00",
        },
    )

    # Assert
    assert response.status_code == 422


# Tests (L, update) that a client cannot inject FX fields on PATCH either.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the request is rejected.
def test_update_expense_endpoint_rejects_injected_fx_fields(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    created = _create_expense_with(
        client=client, user_id=user_id, amount=10, currency="EUR", expense_date="2026-05-07",
    ).json()

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created['id']}",
        json={"fx_rate": "5.00"},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests (M) that FX snapshot resolution and its data stay scoped to the
# authenticated user only.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if a second user's expense list never includes
#   the first user's expense.
def test_create_expense_endpoint_ownership_isolation(
    client: TestClient,
    clean_database: None,
    monkeypatch,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.1539, actual_date="2026-05-07")

    _create_expense_with(
        client=client, user_id=user_id, amount=100, currency="USD", expense_date="2026-05-07",
    )

    # Act
    other_user_expenses = client.get("/api/v1/expenses", headers=auth_headers(other_user_id))

    # Assert
    assert other_user_expenses.json() == []
