from typing import Protocol
from uuid import UUID

from app.models.dynamic_route import DynamicRoute


class DynamicRouteRepository(Protocol):
    async def get_by_id(self, route_id: UUID) -> DynamicRoute | None: ...

    async def get_by_route(
        self,
        *,
        prefix: str,
        path: str,
    ) -> DynamicRoute | None: ...

    async def list_all(self) -> list[DynamicRoute]: ...

    async def create(self, route: DynamicRoute) -> DynamicRoute: ...

    async def update(self, route: DynamicRoute) -> DynamicRoute: ...

    async def delete(self, route: DynamicRoute) -> None: ...
