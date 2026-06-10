from typing import Protocol
from uuid import UUID

from app.models.authorization import ApiPermission, Role, UserRoleAssignment


class AuthorizationRepository(Protocol):
    async def list_roles(self) -> list[Role]: ...

    async def get_role(self, role_id: UUID) -> Role | None: ...

    async def get_role_by_code(self, code: str) -> Role | None: ...

    async def get_user_role_codes(self, user_id: UUID) -> list[str]: ...

    async def assign_role(
        self,
        *,
        user_id: UUID,
        role_id: UUID,
    ) -> UserRoleAssignment: ...

    async def remove_role(
        self,
        *,
        user_id: UUID,
        role_id: UUID,
    ) -> bool: ...

    async def list_permissions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[ApiPermission]: ...

    async def get_permission(self, permission_id: UUID) -> ApiPermission | None: ...

    async def get_permission_by_route_prefix(
        self,
        route_prefix: str,
    ) -> ApiPermission | None: ...

    async def create_permission(self, permission: ApiPermission) -> ApiPermission: ...

    async def update_permission(
        self,
        permission: ApiPermission,
        values: dict[str, object],
    ) -> ApiPermission: ...

    async def delete_permission(self, permission: ApiPermission) -> None: ...

    async def assign_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> None: ...

    async def remove_permission(
        self,
        *,
        user_id: UUID,
        permission_id: UUID,
    ) -> bool: ...

    async def user_has_permission_for_route(
        self,
        *,
        user_id: UUID,
        route_path: str,
    ) -> bool: ...
