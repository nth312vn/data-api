from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import hash_password, verify_password
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.user import User
from app.repositories.interfaces.authorization import AuthorizationRepository
from app.repositories.interfaces.user import UserRepository
from app.schemas.auth import ChangePasswordRequest
from app.schemas.user import UserAdminCreate, UserAdminUpdate, UserUpdate


class UserService:
    def __init__(
        self,
        *,
        users: UserRepository,
        uow: UnitOfWork,
        settings: Settings,
        authorization: AuthorizationRepository | None = None,
    ) -> None:
        self.users = users
        self.uow = uow
        self.settings = settings
        self.authorization = authorization

    async def create_user(self, payload: UserAdminCreate) -> User:
        await self._ensure_unique_identity(
            email=payload.email,
            username=payload.username,
        )

        user = User(
            email=payload.email,
            username=payload.username,
            hashed_password=hash_password(
                payload.password,
                rounds=self.settings.password_bcrypt_rounds,
            ),
            full_name=payload.full_name,
            is_active=payload.is_active,
            role=payload.role,
        )

        try:
            created = await self.users.create(user)
            await self._assign_legacy_role(created)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("User already exists") from exc

        return created

    async def list_users(self, *, limit: int, offset: int) -> list[User]:
        return await self.users.list_users(limit=limit, offset=offset)

    async def get_user(self, user_id: UUID) -> User:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")
        return user

    async def update_profile(self, current_user: User, payload: UserUpdate) -> User:
        updates = payload.model_dump(exclude_unset=True)

        if "username" in updates and updates["username"] != current_user.username:
            existing = await self.users.get_by_username(str(updates["username"]))
            if existing is not None and existing.id != current_user.id:
                raise ConflictError(
                    "Username is already registered",
                    code="username_exists",
                )

        try:
            user = await self.users.update(current_user, updates)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("User profile conflicts with existing data") from exc

        return user

    async def change_password(
        self,
        current_user: User,
        payload: ChangePasswordRequest,
    ) -> None:
        if not verify_password(payload.current_password, current_user.hashed_password):
            raise AuthenticationError("Invalid current password")

        hashed_password = hash_password(
            payload.new_password,
            rounds=self.settings.password_bcrypt_rounds,
        )
        await self.users.update(current_user, {"hashed_password": hashed_password})
        await self.uow.commit()

    async def update_user(self, user_id: UUID, payload: UserAdminUpdate) -> User:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        updates = payload.model_dump(exclude_unset=True)

        email = updates.get("email")
        username = updates.get("username")
        await self._ensure_unique_identity(
            email=str(email) if email is not None else None,
            username=str(username) if username is not None else None,
            current_user=user,
        )

        password = updates.pop("password", None)
        if password is not None:
            updates["hashed_password"] = hash_password(
                str(password),
                rounds=self.settings.password_bcrypt_rounds,
            )

        try:
            updated = await self.users.update(user, updates)
            if "role" in updates:
                await self._assign_legacy_role(updated)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("User conflicts with existing data") from exc

        return updated

    async def delete_account(self, current_user: User) -> None:
        await self.users.delete(current_user)
        await self.uow.commit()

    async def delete_user(self, user_id: UUID) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        await self.users.delete(user)
        await self.uow.commit()

    async def _ensure_unique_identity(
        self,
        *,
        email: str | None = None,
        username: str | None = None,
        current_user: User | None = None,
    ) -> None:
        if email is not None and (current_user is None or email != current_user.email):
            existing = await self.users.get_by_email(email)
            if existing is not None and (
                current_user is None or existing.id != current_user.id
            ):
                raise ConflictError("Email is already registered", code="email_exists")

        if username is not None and (
            current_user is None or username != current_user.username
        ):
            existing = await self.users.get_by_username(username)
            if existing is not None and (
                current_user is None or existing.id != current_user.id
            ):
                raise ConflictError(
                    "Username is already registered",
                    code="username_exists",
                )

    async def _assign_legacy_role(self, user: User) -> None:
        if self.authorization is None:
            return

        role = await self.authorization.get_role_by_code(user.role.value)
        role_codes = await self.authorization.get_user_role_codes(user.id)
        if role is not None and role.code not in role_codes:
            await self.authorization.assign_role(user_id=user.id, role_id=role.id)
