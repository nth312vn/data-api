from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.services.auth import AuthService


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
        user.role = UserRole.user
        user.is_active = True
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
async def test_register_creates_user(settings: Settings) -> None:
    repo = FakeUserRepository()
    uow = FakeUnitOfWork()
    service = AuthService(users=repo, uow=uow, settings=settings)

    user = await service.register(
        UserCreate(
            email="USER@example.com",
            username="ExampleUser",
            password="a-very-secure-password",
        ),
    )

    assert user.email == "user@example.com"
    assert user.username == "exampleuser"
    assert uow.committed


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(settings: Settings) -> None:
    repo = FakeUserRepository()
    existing = User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        is_active=True,
        role=UserRole.user,
    )
    repo.users.append(existing)
    service = AuthService(users=repo, uow=FakeUnitOfWork(), settings=settings)

    with pytest.raises(ConflictError):
        await service.register(
            UserCreate(
                email="user@example.com",
                username="another",
                password="a-very-secure-password",
            ),
        )


@pytest.mark.asyncio
async def test_login_rejects_bad_password(settings: Settings) -> None:
    repo = FakeUserRepository()
    repo.users.append(
        User(
            id=uuid4(),
            email="user@example.com",
            username="user",
            hashed_password=hash_password("a-very-secure-password", rounds=4),
            is_active=True,
            role=UserRole.user,
        ),
    )
    service = AuthService(users=repo, uow=FakeUnitOfWork(), settings=settings)

    with pytest.raises(AuthenticationError):
        await service.login(
            LoginRequest(username="user", password="wrong-password"),
        )
