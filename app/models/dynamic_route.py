import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModelMixin


class DynamicRouteDatabaseType(StrEnum):
    trino = "trino"
    postgres = "postgres"


class DynamicRoutePiiType(StrEnum):
    account_id = "account_id"
    customer_id = "customer_id"


class DynamicRouteResponseType(StrEnum):
    paginated = "paginated"
    data = "data"


class DynamicRoute(BaseModelMixin, Base):
    __tablename__ = "dynamic_routes"
    __table_args__ = (
        UniqueConstraint(
            "prefix",
            "path",
            name="uq_dynamic_routes_prefix_path",
        ),
        CheckConstraint(
            "prefix = lower(prefix)",
            name="ck_dynamic_routes_prefix_lower",
        ),
        CheckConstraint(
            "path <> ''",
            name="ck_dynamic_routes_path_not_empty",
        ),
        CheckConstraint(
            "path NOT LIKE '/%' AND path NOT LIKE '%/'",
            name="ck_dynamic_routes_path_relative",
        ),
        CheckConstraint(
            "position('//' in path) = 0",
            name="ck_dynamic_routes_path_segments",
        ),
        Index("ix_dynamic_routes_prefix", "prefix"),
        Index("ix_dynamic_routes_created_by", "created_by"),
        Index("ix_dynamic_routes_updated_at", "updated_at"),
    )

    prefix: Mapped[str] = mapped_column(String(50), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    original_sql: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_sql: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_definitions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    db_type: Mapped[DynamicRouteDatabaseType] = mapped_column(
        Enum(DynamicRouteDatabaseType, name="dynamic_route_db_type"),
        nullable=False,
        default=DynamicRouteDatabaseType.trino,
        server_default=DynamicRouteDatabaseType.trino.value,
    )
    pii_type: Mapped[DynamicRoutePiiType | None] = mapped_column(
        Enum(DynamicRoutePiiType, name="dynamic_route_pii_type"),
        nullable=True,
        default=None,
    )
    response_type: Mapped[DynamicRouteResponseType] = mapped_column(
        Enum(DynamicRouteResponseType, name="dynamic_route_response_type"),
        nullable=False,
        default=DynamicRouteResponseType.data,
        server_default=DynamicRouteResponseType.data.value,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    @property
    def api_path(self) -> str:
        return f"/{self.prefix}/{self.path}"
