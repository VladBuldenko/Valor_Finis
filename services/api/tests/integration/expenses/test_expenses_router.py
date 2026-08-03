from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, create_category, create_expense

# Tests that the API creates a new expense successfully.
# This test exists to verify the full request flow: router -> auth dependency -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_create_expense_endpoint_creates_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 201
    assert response_data["user_id"] == user_id
    assert response_data["category_id"] is None
    assert response_data["title"] == payload["title"]
    assert response_data["amount"] == "24.99"
    assert response_data["currency"] == payload["currency"]
    assert response_data["expense_date"] == payload["expense_date"]
    assert response_data["description"] == payload["description"]
    assert response_data["source"] == payload["source"]
    assert "id" in response_data
    assert "created_at" in response_data
    assert "updated_at" in response_data


# Tests that the API returns expenses for the authenticated user only.
# This test exists to verify that saved expenses are filtered by the user resolved from authentication data.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains only the authenticated user's expense.
def test_get_expenses_endpoint_returns_authenticated_user_expenses(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )
    create_expense(
        client=client,
        user_id=other_user_id,
        category_id=None,
        title="Train ticket",
        amount=12.50,
    )

    # Act
    response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    # Assert
    response_data = response.json()

    assert response.status_code == 200
    assert len(response_data) == 1
    assert response_data[0]["user_id"] == user_id
    assert response_data[0]["category_id"] is None
    assert response_data[0]["title"] == "Lidl groceries"
    assert response_data[0]["amount"] == "24.99"
    assert response_data[0]["currency"] == "EUR"
    assert response_data[0]["expense_date"] == "2026-05-07"
    assert response_data[0]["description"] == "Lidl groceries"
    assert response_data[0]["source"] == "manual"


# Tests that the API rejects an expense with zero amount.
# This test exists to verify that request validation works before database persistence.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_expense_endpoint_rejects_zero_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": None,
        "title": "Invalid expense",
        "amount": 0,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Invalid expense",
        "source": "manual",
    }

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects requests without authentication header.
# This test exists to verify that the temporary auth dependency protects the expenses endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_get_expenses_endpoint_rejects_missing_user_header(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.get("/api/v1/expenses")

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."

# Tests that the API updates an authenticated user's expense.
# This test exists to verify the PATCH flow: router -> service -> repository -> PostgreSQL.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the response contains updated expense data.
def test_update_expense_endpoint_updates_authenticated_user_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    payload = {
        "title": "Updated groceries",
        "amount": 35.50,
    }

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created_expense['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    response_data = response.json()

    assert response_data["id"] == created_expense["id"]
    assert response_data["user_id"] == user_id
    assert response_data["category_id"] is None
    assert response_data["title"] == "Updated groceries"
    assert response_data["amount"] == "35.50"
    assert response_data["currency"] == "EUR"
    assert response_data["expense_date"] == "2026-05-07"
    assert response_data["description"] == "Lidl groceries"
    assert response_data["source"] == "manual"


# Tests that the API rejects updating another user's expense.
# This test exists to verify ownership protection for PATCH requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_update_expense_endpoint_rejects_other_user_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_expense = create_expense(
        client=client,
        user_id=other_user_id,
        category_id=None,
        title="Train ticket",
        amount=12.50,
    )

    payload = {
        "amount": 15.00,
    }

    # Act
    response = client.patch(
        f"/api/v1/expenses/{other_user_expense['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Expense not found."


# Tests that the API rejects empty expense update payloads.
# This test exists to verify that PATCH requests must contain at least one editable field.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_expense_endpoint_rejects_empty_payload(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created_expense['id']}",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API rejects expense updates with invalid amount.
# This test exists to verify that PATCH validation prevents zero or negative amounts.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_expense_endpoint_rejects_zero_amount(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    payload = {
        "amount": 0,
    }

    # Act
    response = client.patch(
        f"/api/v1/expenses/{created_expense['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that the API deletes an authenticated user's expense.
# This test exists to verify the DELETE flow and that deleted expenses no longer appear in the list.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns no content and the expense is removed.
def test_delete_expense_endpoint_deletes_authenticated_user_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    created_expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    # Act
    delete_response = client.delete(
        f"/api/v1/expenses/{created_expense['id']}",
        headers=auth_headers(user_id),
    )

    get_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    # Assert
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert get_response.status_code == 200
    assert get_response.json() == []


# Tests that the API rejects deleting another user's expense.
# This test exists to verify ownership protection for DELETE requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found status code.
def test_delete_expense_endpoint_rejects_other_user_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_expense = create_expense(
        client=client,
        user_id=other_user_id,
        category_id=None,
        title="Train ticket",
        amount=12.50,
    )

    # Act
    response = client.delete(
        f"/api/v1/expenses/{other_user_expense['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Expense not found."

    # Tests that an expense can use a category owned by the authenticated user.
# This test exists to verify valid category ownership during expense creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_create_expense_endpoint_allows_authenticated_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    payload = {
        "category_id": category["id"],
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 201, response.text
    assert response.json()["category_id"] == category["id"]
    assert response.json()["user_id"] == user_id

    # Tests that an expense cannot use another user's category.
# This test exists to prevent cross-user category assignment.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_create_expense_endpoint_rejects_other_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    other_user_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    payload = {
        "category_id": other_user_category["id"],
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found."

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert expenses_response.json() == []

    # Tests that an expense cannot use a category that does not exist.
# This test exists to return a controlled API error
# instead of relying only on a database foreign key failure.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_create_expense_endpoint_rejects_missing_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "category_id": str(uuid4()),
        "title": "Lidl groceries",
        "amount": 24.99,
        "currency": "EUR",
        "expense_date": "2026-05-07",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act
    response = client.post(
        "/api/v1/expenses",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found."


    # Tests that an expense can be assigned to a category owned by the user.
# This test exists to verify valid category ownership during PATCH requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_update_expense_endpoint_allows_authenticated_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    # Act
    response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        json={
            "category_id": category["id"],
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["category_id"] == category["id"]

    # Tests that an expense cannot be assigned to another user's category.
# This test exists to prevent cross-user category assignment during updates.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_update_expense_endpoint_rejects_other_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=24.99,
    )

    other_user_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

    # Act
    response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        json={
            "category_id": other_user_category["id"],
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found."

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert expenses_response.json()[0]["category_id"] is None

    # Tests that an expense category can be explicitly cleared.
# This test exists to distinguish category_id=null
# from an omitted category_id field during PATCH.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_update_expense_endpoint_clears_category_with_null(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=category["id"],
        title="Lidl groceries",
        amount=24.99,
    )

    # Act
    response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        json={
            "category_id": None,
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["category_id"] is None

    # Tests that an omitted category_id does not change the existing category.
# This test exists to verify correct partial update semantics.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None.
def test_update_expense_endpoint_keeps_category_when_field_is_omitted(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

    expense = create_expense(
        client=client,
        user_id=user_id,
        category_id=category["id"],
        title="Lidl groceries",
        amount=24.99,
    )

    # Act
    response = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        json={
            "title": "Updated groceries",
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Updated groceries"
    assert response.json()["category_id"] == category["id"]