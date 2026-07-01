from typing import Any

from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import DataRowsResponse, MissingPiiMapping
from app.services.data_query.pii_mapper import PiiMapper
from app.services.data_query.routes import DataRouteSpec


class BaseDataQueryService:
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
        spec: DataRouteSpec,
    ) -> DataRowsResponse:
        if not spec.effective_pii_fields:
            return await self._execute_route_without_pii(spec=spec)
        return await self._execute_route_with_pii(spec=spec)

    async def _execute_route_without_pii(
        self,
        *,
        spec: DataRouteSpec,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        return DataRowsResponse(
            rows=rows,
            missing_mappings=[],
        )

    async def _execute_route_with_pii(
        self,
        *,
        spec: DataRouteSpec,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        mapped_rows, missing_keys = await self.pii_mapper.map_pii_fields(
            rows=rows,
            spec=spec,
        )

        missing_mappings = [
            MissingPiiMapping(
                pii_type=key.pii_type,
                token=key.token,
            )
            for key in sorted(
                missing_keys,
                key=lambda key: (key.pii_type, key.token),
            )
        ]

        return DataRowsResponse(
            rows=mapped_rows,
            missing_mappings=missing_mappings,
        )

