from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.user import User, UserRole
from app.repositories.interfaces.user import UserRepository
from app.schemas.auth import LoginRequest, TokenPair
from app.schemas.user import UserCreate


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        uow: UnitOfWork,
        settings: Settings,
    ) -> None:
        self.users = users
        self.uow = uow
        self.settings = settings

    async def register(self, payload: UserCreate) -> User:
        if payload.email is not None and await self.users.get_by_email(payload.email):
            raise ConflictError("Email is already registered", code="email_exists")
        if await self.users.get_by_username(payload.username):
            raise ConflictError(
                "Username is already registered",
                code="username_exists",
            )

        user = User(
            email=payload.email,
            username=payload.username,
            hashed_password=hash_password(
                payload.password,
                rounds=self.settings.password_bcrypt_rounds,
            ),
            role=UserRole.user,
        )

        try:
            created = await self.users.create(user)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("User already exists") from exc

        return created

    async def login(self, payload: LoginRequest) -> TokenPair:
        user = await self.users.get_by_username(payload.username)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise AuthenticationError("Invalid username or password")
        return await self._create_token_pair(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(
            refresh_token,
            settings=self.settings,
            expected_type="refresh",
        )
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise AuthenticationError("Invalid token subject")

        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise AuthenticationError("Invalid token subject") from exc

        user = await self.users.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Invalid refresh token")

        return await self._create_token_pair(user)

    async def _create_token_pair(self, user: User) -> TokenPair:
        extra_claims = {
            "role": user.role.value,
            "username": user.username,
        }
        access_token = create_access_token(
            subject=str(user.id),
            settings=self.settings,
            extra_claims=extra_claims,
        )
        refresh_token = create_refresh_token(
            subject=str(user.id),
            settings=self.settings,
            extra_claims=extra_claims,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
