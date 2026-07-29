from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dynamic_route import DynamicRoute


class SQLAlchemyDynamicRouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, route_id: UUID) -> DynamicRoute | None:
        statement = select(DynamicRoute).where(DynamicRoute.id == route_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_route(
        self,
        *,
        prefix: str,
        path: str,
    ) -> DynamicRoute | None:
        statement = select(DynamicRoute).where(
            DynamicRoute.prefix == prefix,
            DynamicRoute.path == path,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[DynamicRoute]:
        statement = select(DynamicRoute).order_by(
            DynamicRoute.prefix,
            DynamicRoute.path,
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, route: DynamicRoute) -> DynamicRoute:
        self.session.add(route)
        await self.session.flush()
        await self.session.refresh(route)
        return route

    async def update(self, route: DynamicRoute) -> DynamicRoute:
        await self.session.flush()
        await self.session.refresh(route)
        return route

    async def delete(self, route: DynamicRoute) -> None:
        await self.session.delete(route)
        await self.session.flush()
