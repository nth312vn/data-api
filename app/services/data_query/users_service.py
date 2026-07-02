from app.schemas.common import DataRowsResponse
from app.services.data_query.routes import DataRouteSpec
from app.services.data_query.service import BaseDataQueryService
from app.services.data_query.users import build_users_query


class UsersDataService(BaseDataQueryService):
    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="data.users",
            statement=build_users_query(limit=limit, offset=offset),
            pii_field_rules={"customer_id": "customer_id"},
        )
        return await self._execute_route(spec=spec)
