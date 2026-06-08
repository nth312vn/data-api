from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.user import User
from app.repositories.interfaces.user import UserRepository
from app.schemas.user import UserUpdate


class UserService:
    def __init__(self, *, users: UserRepository, uow: UnitOfWork) -> None:
        self.users = users
        self.uow = uow

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

    async def delete_account(self, current_user: User) -> None:
        await self.users.delete(current_user)
        await self.uow.commit()
