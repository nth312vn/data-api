from typing import Any

from app.schemas.common import DataRowsResponse, MissingPiiMapping
from app.services.query_engine.base_service import (
    BaseQueryService,
    QueryExecutionOutcome,
)
from app.services.query_engine.pii_rules import QuerySpec
from app.services.query_engine.users_query import build_users_query
from app.services.query_engine.users_rules import USERS_PII_RULES


class UsersDataService(BaseQueryService):
    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
    ) -> QueryExecutionOutcome[DataRowsResponse]:
        spec = QuerySpec(
            route_name="data.users",
            statement=build_users_query(limit=limit, offset=offset),
            column_pii_rules=USERS_PII_RULES,
        )
        return await self.execute(
            spec=spec,
            response_factory=_build_data_rows_response,
        )


def _build_data_rows_response(
    rows: list[dict[str, Any]],
    missing_mappings: tuple[MissingPiiMapping, ...],
) -> DataRowsResponse:
    return DataRowsResponse(
        rows=rows,
        missing_mappings=list(missing_mappings),
    )
