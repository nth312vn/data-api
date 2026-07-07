from app.schemas.common import DataRowsResponse
from app.services.query_engine.pii_rules import QuerySpec
from app.services.query_engine.base_service import BaseQueryService
from app.services.query_engine.users_query import build_users_query
from app.services.query_engine.users_rules import USERS_PII_RULES


class UsersDataService(BaseQueryService):
    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
    ) -> DataRowsResponse:
        spec = QuerySpec(
            route_name="data.users",
            statement=build_users_query(limit=limit, offset=offset),
            column_pii_rules=USERS_PII_RULES,
        )
        return await self._execute_route(spec=spec)
