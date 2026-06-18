from enum import StrEnum

from sqlalchemy import Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModelMixin


class UserRole(StrEnum):
    user = "user"
    admin = "admin"


class User(BaseModelMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email", "email", unique=True),
        Index("uq_users_username", "username", unique=True),
    )

    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        server_default=UserRole.user.value,
        index=True,
    )
