import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


# Defines the categories table for user expense classification.
# This class exists so expenses and budgets can be grouped by category.
# Fields:
# - id: unique category identifier.
# - user_id: owner of the category.
# - name: visible category name.
# - color: optional UI color.
# - icon: optional UI icon name.
# - is_default: marks predefined categories.
# - created_at: record creation timestamp.
# - updated_at: record update timestamp.
class CategoryModel(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    color: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )

    icon: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    system_key: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_categories_user_id_name_lower",
            user_id,
            func.lower(name),
            unique=True,
        ),
        Index(
            "uq_categories_user_id_system_key",
            user_id,
            system_key,
            unique=True,
        ),
    )