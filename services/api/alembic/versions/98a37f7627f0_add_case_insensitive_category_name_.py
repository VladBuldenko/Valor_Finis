"""add case insensitive category name uniqueness

Revision ID: 98a37f7627f0
Revises: 522bc34f99ed
Create Date: 2026-08-03 08:09:29.615174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98a37f7627f0'
down_revision: Union[str, Sequence[str], None] = '522bc34f99ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_categories_user_id_name",
        "categories",
        type_="unique",
    )

    op.create_index(
        "uq_categories_user_id_name_lower",
        "categories",
        [
            "user_id",
            sa.text("lower(name)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_categories_user_id_name_lower",
        table_name="categories",
    )

    op.create_unique_constraint(
        "uq_categories_user_id_name",
        "categories",
        [
            "user_id",
            "name",
        ],
    )