from typing import Protocol
from uuid import UUID

from app.models.user import User


class UserRepository(Protocol):
    async def get_by_id(
        self,
        user_id: UUID,
    ) -> User | None: ...

    async def get_by_email(
        self,
        email: str,
    ) -> User | None: ...

    async def get_by_username(
        self,
        username: str,
    ) -> User | None: ...

    async def get_admin_user(self) -> User | None: ...

    async def create(self, user: User) -> User: ...

    async def update(self, user: User, values: dict[str, object]) -> User: ...

    async def delete(self, user: User) -> None: ...
