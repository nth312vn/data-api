import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from app.core.config import Settings
from app.core.logging import get_logger
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import MissingPiiMapping
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import QuerySpec

logger = get_logger(__name__)

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True, slots=True)
class QueryExecutionOutcome(Generic[ResponseT]):
    response: ResponseT
    missing_mappings: tuple[MissingPiiMapping, ...] = ()


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

    async def execute(
        self,
        *,
        spec: QuerySpec,
        response_factory: Callable[
            [list[dict[str, Any]], tuple[MissingPiiMapping, ...]],
            ResponseT,
        ],
    ) -> QueryExecutionOutcome[ResponseT]:
        started_at = time.perf_counter()
        status = "failed"
        log_level = logging.ERROR

        try:
            rows = await self.trino.execute(spec.statement)
            missing_mappings: tuple[MissingPiiMapping, ...] = ()
            if spec.pii_columns:
                rows, missing = await self.pii_mapper.map_pii_fields(
                    rows=rows,
                    spec=spec,
                )
                missing_mappings = tuple(missing)

            response = response_factory(rows, missing_mappings)
            status = "success"
            log_level = logging.INFO
            return QueryExecutionOutcome(
                response=response,
                missing_mappings=missing_mappings,
            )
        except asyncio.CancelledError:
            status = "cancelled"
            log_level = logging.WARNING
            raise
        finally:
            logger.log(
                log_level,
                "query_execution_completed route_name=%s status=%s "
                "duration_ms=%.3f",
                spec.route_name,
                status,
                (time.perf_counter() - started_at) * 1000,
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
