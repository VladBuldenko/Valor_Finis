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


# Tests that the account_transactions table exists at HEAD with the
# expected columns, constraints, and foreign key.
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
        "transaction_date", "description", "created_at",
    }

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("account_transactions")
    }
    assert "ck_account_transactions_amount_positive" in check_constraints
    assert "ck_account_transactions_kind_valid" in check_constraints
    assert "ck_account_transactions_direction_valid" in check_constraints

    foreign_keys = inspector.get_foreign_keys("account_transactions")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["referred_table"] == "accounts"
    assert foreign_keys[0]["options"].get("ondelete") == "RESTRICT"

    index_names = {index["name"] for index in inspector.get_indexes("account_transactions")}
    assert "uq_account_transactions_one_opening_balance_per_account" in index_names
