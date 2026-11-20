from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from tests.helpers import auth_headers, create_account

# VF-MVP-BETA-001 (BE-3 / M16): opt-in limit/offset/total pagination of
# GET /api/v1/expenses and the owner-scoped single-record read that keeps an
# older record reachable once the list is paged. Records are created through
# the real API, so every page is read from PostgreSQL by the real LIMIT/OFFSET.

URL = "/api/v1/expenses"
TOTAL_RECORDS = 120
DATE_FIELD = "expense_date"


def _seed(client: TestClient, user_id: str, count: int, day: str = "") -> list[dict]:
    """Creates `count` records with distinct dates (unless `day` is given)."""
    created = []

    for index in range(count):
        # Dates descend through 2026-01..2026-04 so the oldest seeded record
        # is far beyond any first page.
        record_day = day or f"2026-{1 + (index // 28):02d}-{1 + (index % 28):02d}"
        response = client.post(
            URL,
            headers=auth_headers(user_id),
            json={
                "category_id": None, "title": f"Expense {index:03d}", "amount": "10.00",
                "currency": "EUR", "expense_date": record_day,
                "description": None, "source": "manual",
            },
        )
        assert response.status_code == 201, response.text
        created.append(response.json())

    return created


def _ids(items: list[dict]) -> list[str]:
    return [item["id"] for item in items]


def _page(client: TestClient, user_id: str, **params: object) -> dict:
    response = client.get(URL, headers=auth_headers(user_id), params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def seeded(client: TestClient, clean_database: None) -> tuple[str, list[dict]]:
    user_id = str(uuid4())
    return user_id, _seed(client, user_id, TOTAL_RECORDS)


# Without limit/offset the endpoint must keep returning the complete bare
# list exactly as the shipped client expects it.
def test_legacy_request_without_parameters_returns_the_complete_bare_list(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, created = seeded

    response = client.get(URL, headers=auth_headers(user_id))

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == TOTAL_RECORDS
    assert set(_ids(body)) == set(_ids(created))
    assert [item[DATE_FIELD] for item in body] == sorted(
        (item[DATE_FIELD] for item in body), reverse=True,
    )


# First, middle and final pages: sizes, offsets, echoed parameters, total.
def test_first_middle_and_final_pages(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded

    first = _page(client, user_id, limit=50, offset=0)
    middle = _page(client, user_id, limit=50, offset=50)
    final = _page(client, user_id, limit=50, offset=100)

    assert set(first) == {"items", "total", "limit", "offset"}
    assert [len(page["items"]) for page in (first, middle, final)] == [50, 50, 20]
    assert [page["total"] for page in (first, middle, final)] == [TOTAL_RECORDS] * 3
    assert [(page["limit"], page["offset"]) for page in (first, middle, final)] == [
        (50, 0), (50, 50), (50, 100),
    ]


# Walking every page reproduces the legacy list exactly: same records, same
# order, none repeated, none skipped.
def test_concatenated_pages_equal_the_legacy_list(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded
    legacy = client.get(URL, headers=auth_headers(user_id)).json()

    walked: list[dict] = []
    for offset in range(0, TOTAL_RECORDS, 17):
        walked.extend(_page(client, user_id, limit=17, offset=offset)["items"])

    assert _ids(walked) == _ids(legacy)
    assert walked == legacy


# Only offset, or only limit, also requests pagination, with documented defaults.
def test_limit_alone_and_offset_alone_apply_defaults(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded

    only_limit = _page(client, user_id, limit=7)
    only_offset = _page(client, user_id, offset=110)

    assert (only_limit["limit"], only_limit["offset"], len(only_limit["items"])) == (7, 0, 7)
    assert (only_offset["limit"], only_offset["offset"], len(only_offset["items"])) == (50, 110, 10)
    assert only_limit["total"] == only_offset["total"] == TOTAL_RECORDS


def test_the_largest_allowed_page_is_accepted(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded

    page = _page(client, user_id, limit=100)

    assert len(page["items"]) == 100
    assert page["total"] == TOTAL_RECORDS


# Empty results: a user with nothing, and an offset beyond the end.
def test_empty_results(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())

    assert _page(client, user_id, limit=20) == {"items": [], "total": 0, "limit": 20, "offset": 0}

    _seed(client, user_id, 3)
    past_end = _page(client, user_id, limit=20, offset=500)

    assert past_end == {"items": [], "total": 3, "limit": 20, "offset": 500}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"limit": 1000000},
        {"limit": "ten"},
        {"offset": -1},
        {"offset": "ten"},
        {"limit": 10, "offset": -5},
        {"limit": ""},
    ],
)
def test_invalid_pagination_parameters_are_rejected(
    client: TestClient, clean_database: None, params: dict,
) -> None:
    user_id = str(uuid4())
    _seed(client, user_id, 2)

    response = client.get(URL, headers=auth_headers(user_id), params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# Same-day records: the order must be total and stable, so pages never swap,
# repeat or skip rows (date DESC, created_at DESC, id DESC).
def test_tied_dates_are_ordered_deterministically_across_pages(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    _seed(client, user_id, 30, day="2026-03-15")

    first_walk: list[str] = []
    second_walk: list[str] = []
    for walk in (first_walk, second_walk):
        for offset in range(0, 30, 7):
            walk.extend(_ids(_page(client, user_id, limit=7, offset=offset)["items"]))

    assert first_walk == second_walk
    assert len(set(first_walk)) == 30
    legacy = client.get(URL, headers=auth_headers(user_id)).json()
    assert first_walk == _ids(legacy)
    # Newest created first within the tied date.
    created_at = [item["created_at"] for item in legacy]
    assert created_at == sorted(created_at, reverse=True)


# When even created_at is identical, id is the final tie-breaker.
def test_identical_dates_and_timestamps_fall_back_to_id_descending(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    created = _seed(client, user_id, 12, day="2026-03-15")

    db_session = SessionLocal()
    try:
        db_session.execute(
            text("UPDATE expenses SET created_at = '2026-03-15 12:00:00+00' WHERE user_id = :u"),
            {"u": user_id},
        )
        db_session.commit()
    finally:
        db_session.close()

    walked: list[str] = []
    for offset in range(0, 12, 5):
        walked.extend(_ids(_page(client, user_id, limit=5, offset=offset)["items"]))

    assert walked == sorted(_ids(created), reverse=True)


# A user sees, counts and pages only their own records.
def test_pages_and_totals_never_include_another_users_records(
    client: TestClient, clean_database: None,
) -> None:
    user_a = str(uuid4())
    user_b = str(uuid4())
    records_a = _seed(client, user_a, 8)
    records_b = _seed(client, user_b, 5)

    page_a = _page(client, user_a, limit=100)
    page_b = _page(client, user_b, limit=100)
    deep_b = _page(client, user_b, limit=100, offset=5)

    assert page_a["total"] == 8 and page_b["total"] == 5
    assert set(_ids(page_a["items"])) == set(_ids(records_a))
    assert set(_ids(page_b["items"])) == set(_ids(records_b))
    assert deep_b == {"items": [], "total": 5, "limit": 100, "offset": 5}
    assert {item["user_id"] for item in page_a["items"]} == {user_a}


def test_unauthenticated_request_is_rejected_even_with_pagination(
    client: TestClient, clean_database: None,
) -> None:
    assert client.get(URL, params={"limit": 10}).status_code == 401


# The Account link shown on each record comes from the ledger projection; a
# page must show the right link for ITS records only, whatever page they are on.
def test_account_links_are_resolved_for_the_records_of_each_page(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)
    records = _seed(client, user_id, 6)
    legacy = client.get(URL, headers=auth_headers(user_id)).json()
    # Link the 2nd newest (first page) and the 5th newest (second page).
    linked_ids = {legacy[1]["id"], legacy[4]["id"]}
    for record_id in linked_ids:
        response = client.patch(
            f"{URL}/{record_id}",
            headers=auth_headers(user_id),
            json={"account_id": account["id"]},
        )
        assert response.status_code == 200, response.text

    legacy_after = client.get(URL, headers=auth_headers(user_id)).json()
    walked = _page(client, user_id, limit=3, offset=0)["items"] + _page(
        client, user_id, limit=3, offset=3,
    )["items"]

    assert walked == legacy_after
    assert {item["id"] for item in walked if item["account_id"] == account["id"]} == linked_ids
    assert len(records) == 6


# Opening a record that is NOT on the first page: GET /{id} returns the
# record exactly as the list shows it.
def test_a_record_far_beyond_the_first_page_can_be_read_by_id(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded
    legacy = client.get(URL, headers=auth_headers(user_id)).json()
    first_page_ids = set(_ids(_page(client, user_id, limit=25)["items"]))
    oldest = legacy[-1]
    assert oldest["id"] not in first_page_ids

    response = client.get(f"{URL}/{oldest['id']}", headers=auth_headers(user_id))

    assert response.status_code == 200
    assert response.json() == oldest


def test_single_record_read_carries_the_account_link(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)
    record = _seed(client, user_id, 1)[0]
    client.patch(
        f"{URL}/{record['id']}", headers=auth_headers(user_id), json={"account_id": account["id"]},
    )

    body = client.get(f"{URL}/{record['id']}", headers=auth_headers(user_id)).json()

    assert body["account_id"] == account["id"]


def test_single_record_read_is_owner_scoped(
    client: TestClient, clean_database: None,
) -> None:
    user_a = str(uuid4())
    user_b = str(uuid4())
    record_a = _seed(client, user_a, 1)[0]

    foreign = client.get(f"{URL}/{record_a['id']}", headers=auth_headers(user_b))
    unknown = client.get(f"{URL}/{uuid4()}", headers=auth_headers(user_b))

    # A foreign id and a missing id are indistinguishable.
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert record_a["title" if "title" in record_a else "source"] not in foreign.text
    assert client.get(f"{URL}/not-a-uuid", headers=auth_headers(user_a)).status_code == 422
    assert client.get(f"{URL}/{record_a['id']}").status_code == 401


# Edit and delete keep working for a record far from the first page, and the
# paged view reflects them with a correct total.
def test_edit_and_delete_of_an_old_record_are_reflected_in_the_pages(
    client: TestClient, seeded: tuple[str, list[dict]],
) -> None:
    user_id, _ = seeded
    legacy = client.get(URL, headers=auth_headers(user_id)).json()
    old_edit, old_delete = legacy[-1], legacy[-2]

    patched = client.patch(
        f"{URL}/{old_edit['id']}", headers=auth_headers(user_id), json={"description": "edited"},
    )
    deleted = client.delete(f"{URL}/{old_delete['id']}", headers=auth_headers(user_id))

    assert patched.status_code == 200 and patched.json()["description"] == "edited"
    assert deleted.status_code == 204
    last = _page(client, user_id, limit=50, offset=50)
    assert last["total"] == TOTAL_RECORDS - 1
    assert old_delete["id"] not in _ids(last["items"])
    assert client.get(f"{URL}/{old_delete['id']}", headers=auth_headers(user_id)).status_code == 404
    assert client.get(f"{URL}/{old_edit['id']}", headers=auth_headers(user_id)).json()[
        "description"
    ] == "edited"


# Retrieval is read-only: pages and single reads change no stored value and
# create no ledger/event row, and Account balances stay as they were.
def test_pagination_reads_do_not_change_any_financial_state(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client=client, user_id=user_id)
    records = _seed(client, user_id, 15)
    for record in records[:5]:
        client.patch(
            f"{URL}/{record['id']}", headers=auth_headers(user_id),
            json={"account_id": account["id"]},
        )

    def snapshot() -> dict:
        db_session = SessionLocal()
        try:
            return {
                "rows": db_session.execute(
                    text("SELECT * FROM expenses WHERE user_id = :u ORDER BY id"), {"u": user_id},
                ).fetchall(),
                "ledger": db_session.execute(
                    text("SELECT * FROM account_transactions WHERE user_id = :u ORDER BY id"),
                    {"u": user_id},
                ).fetchall(),
                "events": db_session.execute(
                    text("SELECT count(*) FROM financial_events WHERE user_id = :u"), {"u": user_id},
                ).scalar(),
                "balances": [
                    (a["id"], a["current_balance"])
                    for a in client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()
                ],
                "total": sum(float(r["amount"]) for r in client.get(URL, headers=auth_headers(user_id)).json()),
            }
        finally:
            db_session.close()

    before = snapshot()
    for offset in range(0, 15, 4):
        _page(client, user_id, limit=4, offset=offset)
    for record in records:
        assert client.get(f"{URL}/{record['id']}", headers=auth_headers(user_id)).status_code == 200
    after = snapshot()

    assert after == before
    # The envelope's total is a record COUNT, not a money amount.
    assert _page(client, user_id, limit=1)["total"] == 15
