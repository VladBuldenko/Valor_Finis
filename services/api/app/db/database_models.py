"""
Database model registry.

What:
    Imports all SQLAlchemy models used by the application.

Why:
    SQLAlchemy must import model classes before it can resolve
    tables, foreign keys, and metadata relationships.

Best practices:
    Keep model registration explicit and centralized.
    Avoid hidden imports inside repositories or services.
"""


# Imports all SQLAlchemy models used by the application.
# This function exists to register all model tables in Base.metadata
# before the application handles database operations.
# Parameters:
# - None.
# Returns:
# - None.
def import_database_models() -> None:
    from app.modules.categories.category_models import CategoryModel
    from app.modules.budgets.budgets_models import BudgetModel
    from app.modules.expenses.expenses_models import ExpenseModel
    from app.modules.goals.goal_models import GoalModel
    from app.modules.receipts.receipt_models import ReceiptModel

    _ = (
        CategoryModel,
        BudgetModel,
        ExpenseModel,
        GoalModel,
        ReceiptModel,
    )