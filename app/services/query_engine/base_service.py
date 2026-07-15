from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import DataRowsResponse
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import QuerySpec


class BaseQueryService:
    def __init__(
        self,
        *,
        settings: Settings,
        trino: TrinoClient,
        pii_mapper: PiiMapper,
        uow: UnitOfWork,
    ) -> None:
        self.settings = settings
        self.trino = trino
        self.pii_mapper = pii_mapper
        self.uow = uow

    async def _execute_route(
        self,
        *,
        spec: QuerySpec,
    ) -> DataRowsResponse:
        if not spec.pii_columns:
            return await self._execute_route_without_pii(spec=spec)
        return await self._execute_route_with_pii(spec=spec)

    async def _execute_route_without_pii(
        self,
        *,
        spec: QuerySpec,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        return DataRowsResponse(
            rows=rows,
            missing_mappings=[],
        )

    def _get_tokens_by_original_values(
        self,
        *,
        original_values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not original_values:
            return ()
        lower_values = {v.casefold() for v in original_values}
        cache = self.pii_mapper.mapping_cache.value_to_token
        tokens = [
            token
            for mapped_value, token in cache.items()
            if mapped_value.casefold() in lower_values
        ]
        if not tokens:
            # Return a dummy token so the query will return an empty result
            # rather than skipping the filter entirely.
            return ("__NO_MATCH__",)
        return tuple(tokens)

    async def _execute_route_with_pii(
        self,
        *,
        spec: QuerySpec,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        mapped_rows, missing_mappings = await self.pii_mapper.map_pii_fields(
            rows=rows,
            spec=spec,
        )

        return DataRowsResponse(
            rows=mapped_rows,
            missing_mappings=missing_mappings,
        )
