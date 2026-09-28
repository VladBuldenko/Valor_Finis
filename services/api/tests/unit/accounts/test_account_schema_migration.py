from sqlalchemy import inspect

from app.db.database_session import engine


# Tests that the accounts table exists at HEAD with no balance column and
# the expected CHECK constraints.
# This test exists as the live-database counterpart to
# test_account_model_has_no_current_balance_column (which only checks the
# ORM mapping): it proves migration 3d7bb3d11671's upgrade() effect
# actually holds in the real schema.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the table, its columns, and its constraints
#   match the migration exactly.
def test_accounts_table_schema_matches_migration() -> None:
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("accounts")}
    assert columns == {
        "id", "user_id", "name", "type", "currency", "status",
        "created_at", "updated_at",
    }
    assert "current_balance" not in columns

    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("accounts")
    }
    assert "ck_accounts_type_valid" in check_constraints
    assert "ck_accounts_status_valid" in check_constraints

    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("accounts")
    }
    assert "uq_accounts_id_user_id" in unique_constraints
    # VF-018B: FK target for account_transfers' currency-bearing
    # composite foreign keys.
    assert "uq_accounts_id_user_id_currency" in unique_constraints


# Tests that the account_transactions table exists at HEAD with the
# expected columns, constraints, and foreign keys, including the VF-017D
# income_id, VF-017E expense_id, and VF-018B transfer_id linkage additions.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the table matches the migration exactly.
def test_account_transactions_table_schema_matches_migration() -> None:
    inspector = inspect(engine)

    columns = {
        column["name"] for column in inspector.get_columns("account_transactions")
    }
    assert columns == {
        "id", "account_id", "user_id", "kind", "direction", "amount",
        "transaction_date", "description", "income_id", "expense_id",
        "transfer_id", "created_at",
    }

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("account_transactions")
    }
    assert "ck_account_transactions_amount_positive" in check_constraints
    assert "ck_account_transactions_kind_valid" in check_constraints
    assert "ck_account_transactions_direction_valid" in check_constraints
    assert "ck_account_transactions_source_linkage_valid" in check_constraints
    assert "ck_account_transactions_income_linkage_valid" not in check_constraints

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("account_transactions")}
    assert "account_transactions_account_id_fkey" in foreign_keys
    assert "fk_account_transactions_account_id_user_id" in foreign_keys
    assert "fk_account_transactions_income_id_user_id" in foreign_keys
    assert "fk_account_transactions_expense_id_user_id" in foreign_keys
    assert "fk_account_transactions_transfer_id_user_id" in foreign_keys

    composite_account_fk = next(
        fk for fk in inspector.get_foreign_keys("account_transactions")
        if fk["name"] == "fk_account_transactions_account_id_user_id"
    )
    assert composite_account_fk["referred_table"] == "accounts"
    assert composite_account_fk["constrained_columns"] == ["account_id", "user_id"]
    assert composite_account_fk["referred_columns"] == ["id", "user_id"]
    assert composite_account_fk["options"].get("ondelete") == "RESTRICT"

    composite_income_fk = next(
        fk for fk in inspector.get_foreign_keys("account_transactions")
        if fk["name"] == "fk_account_transactions_income_id_user_id"
    )
    assert composite_income_fk["referred_table"] == "income"
    assert composite_income_fk["constrained_columns"] == ["income_id", "user_id"]
    assert composite_income_fk["referred_columns"] == ["id", "user_id"]
    assert composite_income_fk["options"].get("ondelete") == "CASCADE"

    composite_expense_fk = next(
        fk for fk in inspector.get_foreign_keys("account_transactions")
        if fk["name"] == "fk_account_transactions_expense_id_user_id"
    )
    assert composite_expense_fk["referred_table"] == "expenses"
    assert composite_expense_fk["constrained_columns"] == ["expense_id", "user_id"]
    assert composite_expense_fk["referred_columns"] == ["id", "user_id"]
    assert composite_expense_fk["options"].get("ondelete") == "CASCADE"

    composite_transfer_fk = next(
        fk for fk in inspector.get_foreign_keys("account_transactions")
        if fk["name"] == "fk_account_transactions_transfer_id_user_id"
    )
    assert composite_transfer_fk["referred_table"] == "account_transfers"
    assert composite_transfer_fk["constrained_columns"] == ["transfer_id", "user_id"]
    assert composite_transfer_fk["referred_columns"] == ["id", "user_id"]
    assert composite_transfer_fk["options"].get("ondelete") == "CASCADE"

    index_names = {index["name"] for index in inspector.get_indexes("account_transactions")}
    assert "uq_account_transactions_one_opening_balance_per_account" in index_names

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("account_transactions")
    }
    assert "uq_account_transactions_income_id" in unique_constraints
    assert "uq_account_transactions_expense_id" in unique_constraints
    assert "uq_account_transactions_transfer_id_direction" in unique_constraints


# Tests that the income table's composite (id, user_id) unique constraint
# exists at HEAD - the FK target the composite ownership foreign key
# above relies on.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the constraint exists.
def test_income_table_has_composite_ownership_unique_constraint() -> None:
    inspector = inspect(engine)

    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("income")
    }
    assert "uq_income_id_user_id" in unique_constraints


# Tests that the expenses table's composite (id, user_id) unique
# constraint exists at HEAD (VF-017E) - the FK target the composite
# ownership foreign key on account_transactions.expense_id relies on.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the constraint exists.
def test_expenses_table_has_composite_ownership_unique_constraint() -> None:
    inspector = inspect(engine)

    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("expenses")
    }
    assert "uq_expenses_id_user_id" in unique_constraints


# Tests that the account_transfers table exists at HEAD (VF-018B) with the
# expected columns, CHECK constraints, unique constraints, currency-bearing
# composite foreign keys, and indexes.
# This test exists as the live-database counterpart to the ORM model: it
# proves migration 1edb74dc96d8's upgrade() effect actually holds in the
# real schema, including that there is no persisted transfer_date column.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the table matches the migration exactly.
def test_account_transfers_table_schema_matches_migration() -> None:
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("account_transfers")}
    assert columns == {
        "id", "user_id", "client_request_id", "source_account_id",
        "destination_account_id", "amount", "currency", "status",
        "planned_date", "effective_date", "description", "posted_at",
        "created_at", "updated_at",
    }
    assert "transfer_date" not in columns

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("account_transfers")
    }
    assert check_constraints >= {
        "ck_account_transfers_amount_positive",
        "ck_account_transfers_distinct_accounts",
        "ck_account_transfers_status_valid",
        "ck_account_transfers_lifecycle_consistent",
    }

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("account_transfers")
    }
    assert "uq_account_transfers_id_user_id" in unique_constraints
    assert "uq_account_transfers_user_id_client_request_id" in unique_constraints

    foreign_keys = {
        fk["name"]: fk for fk in inspector.get_foreign_keys("account_transfers")
    }
    assert set(foreign_keys) == {
        "fk_account_transfers_source_account",
        "fk_account_transfers_destination_account",
    }

    source_fk = foreign_keys["fk_account_transfers_source_account"]
    assert source_fk["referred_table"] == "accounts"
    assert source_fk["constrained_columns"] == [
        "source_account_id", "user_id", "currency",
    ]
    assert source_fk["referred_columns"] == ["id", "user_id", "currency"]
    assert source_fk["options"].get("ondelete") == "RESTRICT"

    destination_fk = foreign_keys["fk_account_transfers_destination_account"]
    assert destination_fk["referred_table"] == "accounts"
    assert destination_fk["constrained_columns"] == [
        "destination_account_id", "user_id", "currency",
    ]
    assert destination_fk["referred_columns"] == ["id", "user_id", "currency"]
    assert destination_fk["options"].get("ondelete") == "RESTRICT"

    index_names = {index["name"] for index in inspector.get_indexes("account_transfers")}
    assert "ix_account_transfers_source_account_id" in index_names
    assert "ix_account_transfers_destination_account_id" in index_names
