import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModelMixin


class AuditLog(BaseModelMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_api_route", "api_route"),
        Index("ix_audit_logs_allowed", "allowed"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    api_route: Mapped[str] = mapped_column(String(500), nullable=False)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_process_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
