from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import ChangePasswordRequest
from app.schemas.user import UserAdminCreate, UserAdminUpdate
from app.services.user import UserService


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: list[User] = []

    async def get_by_id(self, user_id):  # type: ignore[no-untyped-def]
        return next((user for user in self.users if user.id == user_id), None)

    async def get_by_email(self, email):  # type: ignore[no-untyped-def]
        return next((user for user in self.users if user.email == email), None)

    async def get_by_username(self, username):  # type: ignore[no-untyped-def]
        return next((user for user in self.users if user.username == username), None)

    async def get_admin_user(self) -> User | None:
        return next((user for user in self.users if user.role == UserRole.admin), None)

    async def list_users(self, *, limit: int, offset: int) -> list[User]:
        return self.users[offset : offset + limit]

    async def create(self, user: User) -> User:
        user.id = uuid4()
        self.users.append(user)
        return user

    async def update(self, user: User, values: dict[str, object]) -> User:
        for key, value in values.items():
            setattr(user, key, value)
        return user

    async def delete(self, user: User) -> None:
        self.users.remove(user)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret-key-with-at-least-32-chars",
        password_bcrypt_rounds=4,
    )


@pytest.mark.asyncio
async def test_admin_create_user_sets_role_and_hashes_password(
    settings: Settings,
) -> None:
    repo = FakeUserRepository()
    uow = FakeUnitOfWork()
    service = UserService(users=repo, uow=uow, settings=settings)

    user = await service.create_user(
        UserAdminCreate(
            email="ADMIN@example.com",
            username="AdminUser",
            password="a-very-secure-password",
            role=UserRole.admin,
        ),
    )

    assert user.email == "admin@example.com"
    assert user.username == "adminuser"
    assert user.role == UserRole.admin
    assert user.hashed_password != "a-very-secure-password"
    assert verify_password("a-very-secure-password", user.hashed_password)
    assert uow.committed


@pytest.mark.asyncio
async def test_admin_update_user_can_change_password_and_status(
    settings: Settings,
) -> None:
    repo = FakeUserRepository()
    user = User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="old-hash",
        is_active=True,
        role=UserRole.user,
    )
    repo.users.append(user)
    uow = FakeUnitOfWork()
    service = UserService(users=repo, uow=uow, settings=settings)

    updated = await service.update_user(
        user.id,
        UserAdminUpdate(
            password="another-secure-password",
            is_active=False,
            role=UserRole.admin,
        ),
    )

    assert updated.is_active is False
    assert updated.role == UserRole.admin
    assert verify_password("another-secure-password", updated.hashed_password)
    assert uow.committed


@pytest.mark.asyncio
async def test_change_password_verifies_current_password(
    settings: Settings,
) -> None:
    repo = FakeUserRepository()
    user = User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password=hash_password("old-secure-password", rounds=4),
        is_active=True,
        role=UserRole.user,
    )
    repo.users.append(user)
    uow = FakeUnitOfWork()
    service = UserService(users=repo, uow=uow, settings=settings)

    await service.change_password(
        user,
        ChangePasswordRequest(
            current_password="old-secure-password",
            new_password="new-secure-password",
        ),
    )

    assert verify_password("new-secure-password", user.hashed_password)
    assert uow.committed


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(
    settings: Settings,
) -> None:
    repo = FakeUserRepository()
    user = User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password=hash_password("old-secure-password", rounds=4),
        is_active=True,
        role=UserRole.user,
    )
    repo.users.append(user)
    service = UserService(users=repo, uow=FakeUnitOfWork(), settings=settings)

    with pytest.raises(AuthenticationError):
        await service.change_password(
            user,
            ChangePasswordRequest(
                current_password="wrong-password",
                new_password="new-secure-password",
            ),
        )
