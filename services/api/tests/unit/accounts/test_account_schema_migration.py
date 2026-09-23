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


# Tests that the account_transactions table exists at HEAD with the
# expected columns, constraints, and foreign keys, including the VF-017D
# income_id linkage additions.
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
        "transaction_date", "description", "income_id", "created_at",
    }

    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("account_transactions")
    }
    assert "ck_account_transactions_amount_positive" in check_constraints
    assert "ck_account_transactions_kind_valid" in check_constraints
    assert "ck_account_transactions_direction_valid" in check_constraints
    assert "ck_account_transactions_income_linkage_valid" in check_constraints

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("account_transactions")}
    assert "account_transactions_account_id_fkey" in foreign_keys
    assert "fk_account_transactions_account_id_user_id" in foreign_keys
    assert "fk_account_transactions_income_id_user_id" in foreign_keys

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

    index_names = {index["name"] for index in inspector.get_indexes("account_transactions")}
    assert "uq_account_transactions_one_opening_balance_per_account" in index_names

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("account_transactions")
    }
    assert "uq_account_transactions_income_id" in unique_constraints


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
