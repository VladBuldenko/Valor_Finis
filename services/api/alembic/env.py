from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.app_config import settings
from app.db.database_base import Base
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.goals.goals_models import GoalModel


config = context.config


if config.config_file_name is not None:
    fileConfig(config.config_file_name)


config.set_main_option("sqlalchemy.url", settings.database_url)


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run Alembic migrations in offline mode.

    This function configures Alembic using only the database URL.
    It is useful when migrations need to be generated as SQL scripts
    without opening a live database connection.

    Parameters:
    - None.

    Returns:
    - None.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run Alembic migrations in online mode.

    This function creates a live database connection and applies migrations
    directly to the connected PostgreSQL database.

    Parameters:
    - None.

    Returns:
    - None.
    """

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()