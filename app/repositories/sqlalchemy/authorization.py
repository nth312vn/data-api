from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization import (
    ApiPermission,
    Role,
    UserApiPermission,
    UserRoleAssignment,
)


class SQLAlchemyAuthorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_roles(self) -> list[Role]:
        stmt = select(Role).order_by(Role.code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_role(self, role_id: UUID) -> Role | None:
        stmt = select(Role).where(Role.id == role_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_role_by_code(self, code: str) -> Role | None:
        stmt = select(Role).where(Role.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_role_codes(self, user_id: UUID) -> list[str]:
        stmt = (
            select(Role.code)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .order_by(Role.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def assign_role(
        self,
        *,
        user_id: UUID,
        role_id: UUID,
    ) -> UserRoleAssignment:
        assignment = UserRoleAssignment(user_id=user_id, role_id=role_id)
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def remove_role(
        self,
        *,
        user_id: UUID,
        role_id: UUID,
    ) -> bool:
        stmt = select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id == role_id,
        )
        result = await self.session.execute(stmt)
        assignment = result.scalar_one_or_none()
        if assignment is None:
            return False
        await self.session.delete(assignment)
        await self.session.flush()
        return True

    async def list_permissions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[ApiPermission]:
        stmt = (
            select(ApiPermission)
            .order_by(ApiPermission.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_permission(self, permission_id: UUID) -> ApiPermission | None:
        stmt = select(ApiPermission).where(ApiPermission.id == permission_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_permission_by_route_prefix(
        self,
        route_prefix: str,
    ) -> ApiPermission | None:
        stmt = select(ApiPermission).where(ApiPermission.route_prefix == route_prefix)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_permission(self, permission: ApiPermission) -> ApiPermission:
        self.session.add(permission)
        await self.session.flush()
        await self.session.refresh(permission)
        return permission

    async def update_permission(
        self,
        permission: ApiPermission,
        values: dict[str, object],
    ) -> ApiPermission:
        for field, value in values.items():
            setattr(permission, field, value)
        await self.session.flush()
        await self.session.refresh(permission)
        return permission

    async def delete_permission(self, permission: ApiPermission) -> None:
        await self.session.delete(permission)
        await self.session.flush()

    async def assign_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> None:
        self.session.add(
            UserApiPermission(user_id=user_id, permission_id=permission_id),
        )
        await self.session.flush()

    async def remove_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> bool:
        stmt = select(UserApiPermission).where(
            UserApiPermission.user_id == user_id,
            UserApiPermission.permission_id == permission_id,
        )
        result = await self.session.execute(stmt)
        assignment = result.scalar_one_or_none()
        if assignment is None:
            return False
        await self.session.delete(assignment)
        await self.session.flush()
        return True

    async def user_has_permission_for_route(
        self,
        *,
        user_id: UUID,
        route_path: str,
    ) -> bool:
        stmt = (
            select(ApiPermission.route_prefix)
            .join(
                UserApiPermission,
                UserApiPermission.permission_id == ApiPermission.id,
            )
            .where(
                UserApiPermission.user_id == user_id,
                ApiPermission.is_active.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        prefixes = result.scalars().all()
        return any(_route_matches_prefix(route_path, prefix) for prefix in prefixes)


def _route_matches_prefix(route_path: str, route_prefix: str) -> bool:
    normalized_path = route_path.rstrip("/") or "/"
    normalized_prefix = route_prefix.rstrip("/") or "/"
    return normalized_path == normalized_prefix or normalized_path.startswith(
        f"{normalized_prefix}/",
    )
