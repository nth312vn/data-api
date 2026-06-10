from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.authorization import ApiPermission, Role
from app.models.user import UserRole
from app.repositories.interfaces.authorization import AuthorizationRepository
from app.repositories.interfaces.user import UserRepository
from app.schemas.authorization import ApiPermissionCreate, ApiPermissionUpdate


class AuthorizationService:
    def __init__(
        self,
        *,
        authorization: AuthorizationRepository,
        users: UserRepository,
        uow: UnitOfWork,
    ) -> None:
        self.authorization = authorization
        self.users = users
        self.uow = uow

    async def list_roles(self) -> list[Role]:
        return await self.authorization.list_roles()

    async def assign_role(self, *, user_id: UUID, role_id: UUID) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        role = await self.authorization.get_role(role_id)
        if role is None:
            raise NotFoundError("Role")

        try:
            await self.authorization.assign_role(user_id=user_id, role_id=role_id)
            await self._sync_legacy_user_role(user_id)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("Role is already assigned") from exc

    async def remove_role(self, *, user_id: UUID, role_id: UUID) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        removed = await self.authorization.remove_role(
            user_id=user_id,
            role_id=role_id,
        )
        if not removed:
            raise NotFoundError("User role")

        await self._sync_legacy_user_role(user_id)
        await self.uow.commit()

    async def list_permissions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[ApiPermission]:
        return await self.authorization.list_permissions(limit=limit, offset=offset)

    async def get_permission(self, permission_id: UUID) -> ApiPermission:
        permission = await self.authorization.get_permission(permission_id)
        if permission is None:
            raise NotFoundError("API permission")
        return permission

    async def create_permission(
        self,
        payload: ApiPermissionCreate,
    ) -> ApiPermission:
        permission = ApiPermission(**payload.model_dump())
        try:
            created = await self.authorization.create_permission(permission)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("API permission already exists") from exc
        return created

    async def update_permission(
        self,
        permission_id: UUID,
        payload: ApiPermissionUpdate,
    ) -> ApiPermission:
        permission = await self.get_permission(permission_id)
        updates = payload.model_dump(exclude_unset=True)

        try:
            updated = await self.authorization.update_permission(permission, updates)
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("API permission conflicts with existing data") from exc
        return updated

    async def delete_permission(self, permission_id: UUID) -> None:
        permission = await self.get_permission(permission_id)
        await self.authorization.delete_permission(permission)
        await self.uow.commit()

    async def assign_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        permission = await self.authorization.get_permission(permission_id)
        if permission is None:
            raise NotFoundError("API permission")

        try:
            await self.authorization.assign_permission(
                user_id=user_id,
                permission_id=permission_id,
            )
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("API permission is already assigned") from exc

    async def remove_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        removed = await self.authorization.remove_permission(
            user_id=user_id,
            permission_id=permission_id,
        )
        if not removed:
            raise NotFoundError("User API permission")

        await self.uow.commit()

    async def _sync_legacy_user_role(self, user_id: UUID) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            return

        role_codes = await self.authorization.get_user_role_codes(user_id)
        role = UserRole.admin if UserRole.admin.value in role_codes else UserRole.user
        await self.users.update(user, {"role": role})
