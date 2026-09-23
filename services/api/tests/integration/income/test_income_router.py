from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.fx import fx_ecb_provider, fx_nbu_provider
from tests.helpers import auth_headers, create_income


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


# Tests that creating a EUR income record produces a complete identity FX
# snapshot with no HTTP call.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no provider HTTP call happens.
# Returns:
# - None. The test passes if the response carries a complete identity snapshot.
def test_create_income_endpoint_eur_produces_identity_snapshot(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    income = create_income(client=client, user_id=user_id, amount=2500, currency="EUR")

    assert income["base_amount"] == "2500.00"
    assert income["base_currency"] == "EUR"
    assert income["fx_rate"] == "1.00000000"
    assert income["fx_source"] == "identity"
    ecb_mock.assert_not_called()


# Tests that creating a foreign-currency income record resolves a full
# snapshot from the (network-free, mocked) ECB provider.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the response carries the mocked rate.
def test_create_income_endpoint_foreign_currency_resolves_snapshot(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    _mock_ecb(monkeypatch, rate=1.18, actual_date="2026-05-06")

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "USD", "received_at": "2026-05-07",
            "source": "freelance", "description": None,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert body["fx_source"] == "ecb"
    assert body["fx_rate_date"] == "2026-05-06"


# Tests that a future-dated foreign-currency income is rejected with the
# exact Income-specific public error message (not Expense's).
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no HTTP call happens (the
#   future-date rejection happens before any provider is consulted).
# Returns:
# - None. The test passes if the response is 422 with the exact message.
def test_create_income_endpoint_future_dated_foreign_rejected(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "USD", "received_at": "2099-01-01",
            "source": "other", "description": None,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "A foreign-currency income cannot be dated in the future."
    ecb_mock.assert_not_called()


# Tests that a future-dated EUR (base-currency/identity) income is
# accepted - matching Expense's established semantics that the
# future-date restriction only protects historical rate lookups.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if creation succeeds (201).
def test_create_income_endpoint_future_dated_base_currency_accepted(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    income = create_income(
        client=client, user_id=user_id, currency="EUR", received_at="2099-01-01",
    )
    assert income["fx_source"] == "identity"


# Tests that amount is validated as strictly positive.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_income_endpoint_rejects_non_positive_amount(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "0.00", "currency": "EUR", "received_at": "2026-05-07",
            "source": "salary", "description": None,
        },
    )
    assert response.status_code == 422


# Tests that an invalid source is rejected.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_income_endpoint_rejects_invalid_source(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "EUR", "received_at": "2026-05-07",
            "source": "lottery", "description": None,
        },
    )
    assert response.status_code == 422


# Tests that currency is normalized to uppercase.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response reports the uppercased currency.
def test_create_income_endpoint_normalizes_currency(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    income = create_income(client=client, user_id=user_id, currency="eur")
    assert income["currency"] == "EUR"


# Tests that the API rejects a client-supplied FX field on creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_income_endpoint_rejects_injected_fx_fields(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "EUR", "received_at": "2026-05-07",
            "source": "salary", "description": None, "base_amount": "100.00",
        },
    )
    assert response.status_code == 422


# Tests that the API rejects a client-supplied user_id.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_income_endpoint_rejects_user_id_field(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "EUR", "received_at": "2026-05-07",
            "source": "salary", "description": None, "user_id": user_id,
        },
    )
    assert response.status_code == 422


# Tests that the API rejects a client-supplied account_id.
# This test exists as the end-to-end regression for the VF-017C
# architectural rule that account_id must not exist in the public Income
# contract yet.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_create_income_endpoint_rejects_account_id_field(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": "100.00", "currency": "EUR", "received_at": "2026-05-07",
            "source": "salary", "description": None,
            "account_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert response.status_code == 422


# Tests that GET /income returns only the authenticated user's records,
# newest received_at first.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if ownership scoping and ordering are correct.
def test_get_income_endpoint_ownership_and_ordering(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_income(client=client, user_id=user_id, received_at="2026-05-01", source="salary")
    create_income(client=client, user_id=user_id, received_at="2026-05-10", source="gift")
    create_income(client=client, user_id=other_user_id, received_at="2026-05-20", source="refund")

    response = client.get("/api/v1/income", headers=auth_headers(user_id))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert [item["received_at"] for item in data] == ["2026-05-10", "2026-05-01"]


# Tests that PATCH /income/{id} with an amount-only change reuses the
# existing FX snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no HTTP call happens.
# Returns:
# - None. The test passes if the fx snapshot fields are unchanged and
#   base_amount reflects the new amount.
def test_update_income_endpoint_amount_only_preserves_snapshot(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    income = create_income(client=client, user_id=user_id, amount=100, currency="EUR")

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"amount": "150.00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["base_amount"] == "150.00"
    assert body["fx_source"] == "identity"
    ecb_mock.assert_not_called()


# Tests that PATCH /income/{id} with a currency change re-resolves the
# FX snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the response reflects the freshly resolved
#   snapshot.
def test_update_income_endpoint_currency_change_re_resolves(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    income = create_income(client=client, user_id=user_id, amount=100, currency="EUR")

    _mock_ecb(monkeypatch, rate=1.18, actual_date="2026-05-06")

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"currency": "USD"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert body["fx_source"] == "ecb"


# Tests that PATCH /income/{id} with a received_at change re-resolves the
# FX snapshot.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if received_at updates and the (identity)
#   snapshot remains internally consistent for the new date.
def test_update_income_endpoint_received_at_change_re_resolves(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    income = create_income(client=client, user_id=user_id, amount=100, currency="EUR")

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"received_at": "2026-06-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["received_at"] == "2026-06-15"
    assert body["fx_rate_date"] == "2026-06-15"


# Tests that PATCH /income/{id} with only description preserves the
# existing FX snapshot and requires no HTTP call.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no HTTP call happens.
# Returns:
# - None. The test passes if the snapshot is unchanged.
def test_update_income_endpoint_description_only_preserves_snapshot(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    income = create_income(client=client, user_id=user_id, amount=100, currency="EUR")

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"description": "Updated note"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated note"
    assert body["fx_rate"] == income["fx_rate"]
    assert body["base_amount"] == income["base_amount"]
    ecb_mock.assert_not_called()


# Tests that PATCH /income/{id} with only source preserves the existing
# FX snapshot and requires no HTTP call.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# - monkeypatch: pytest fixture used to assert no HTTP call happens.
# Returns:
# - None. The test passes if the snapshot is unchanged.
def test_update_income_endpoint_source_only_preserves_snapshot(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    ecb_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", ecb_mock)

    income = create_income(client=client, user_id=user_id, amount=100, currency="EUR", source="salary")

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"source": "gift"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "gift"
    assert body["fx_rate"] == income["fx_rate"]
    ecb_mock.assert_not_called()


# Tests that PATCH /income/{id} rejects an empty payload.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 422.
def test_update_income_endpoint_rejects_empty_payload(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    income = create_income(client=client, user_id=user_id)

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={},
    )
    assert response.status_code == 422


# Tests that another user cannot update someone else's income record.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 404.
def test_update_income_endpoint_other_user_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    income = create_income(client=client, user_id=other_user_id)

    response = client.patch(
        f"/api/v1/income/{income['id']}",
        headers=auth_headers(user_id),
        json={"source": "gift"},
    )
    assert response.status_code == 404


# Tests that DELETE /income/{id} succeeds (204) for an owned record.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 204 and a subsequent GET no
#   longer includes it.
def test_delete_income_endpoint_owned_record_succeeds(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    income = create_income(client=client, user_id=user_id)

    response = client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(user_id))
    assert response.status_code == 204

    list_response = client.get("/api/v1/income", headers=auth_headers(user_id))
    assert list_response.json() == []


# Tests that DELETE /income/{id} returns 404 for another user's record.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response is 404.
def test_delete_income_endpoint_other_user_not_found(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    income = create_income(client=client, user_id=other_user_id)

    response = client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(user_id))
    assert response.status_code == 404
