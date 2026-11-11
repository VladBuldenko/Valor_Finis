from sqlalchemy import inspect

from app.db.database_session import engine


# Tests that the income table exists at HEAD with the expected columns
# and constraints.
# This test exists as the live-database counterpart to
# test_income_model_has_no_account_id_column (which only checks the ORM
# mapping): it proves migration c6b5afc1cc43's upgrade() effect actually
# holds in the real schema.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the table, its columns, and its constraints
#   match the migration exactly.
def test_income_table_schema_matches_migration() -> None:
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("income")}
    assert columns == {
        "id", "user_id", "amount", "currency", "received_at", "source",
        "description", "base_amount", "base_currency", "fx_rate",
        "fx_rate_date", "fx_source", "created_at", "updated_at",
        # VF-MVP-CORE-002 (revision b8e2c5d1f739): create idempotency.
        "client_request_id", "client_request_fingerprint",
    }
    assert "account_id" not in columns

    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("income")
    }
    assert "ck_income_amount_positive" in check_constraints
    assert "ck_income_source_valid" in check_constraints
    assert "ck_income_base_amount_positive" in check_constraints
    assert "ck_income_fx_rate_positive" in check_constraints
    assert "ck_income_fx_snapshot_all_or_none" in check_constraints
    assert "ck_income_client_request_all_or_none" in check_constraints
    assert "uq_income_user_id_client_request_id" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("income")
    }

    index_names = {index["name"] for index in inspector.get_indexes("income")}
    assert "ix_income_user_id" in index_names
    assert "ix_income_received_at" in index_names

    foreign_keys = inspector.get_foreign_keys("income")
    assert foreign_keys == []
