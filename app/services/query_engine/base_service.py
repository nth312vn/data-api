import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeAlias, TypeVar

from app.core.config import Settings
from app.core.logging import get_logger
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import MissingPiiMapping
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import QuerySpec

logger = get_logger(__name__)

ResponseT = TypeVar("ResponseT")
QueryRows: TypeAlias = list[dict[str, Any]]
ResponseFactory: TypeAlias = Callable[
    [QueryRows, tuple[MissingPiiMapping, ...]],
    ResponseT,
]


@dataclass(frozen=True, slots=True)
class QueryExecutionOutcome(Generic[ResponseT]):
    response: ResponseT
    missing_mappings: tuple[MissingPiiMapping, ...] = field(default_factory=tuple)


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
        response_factory: ResponseFactory[ResponseT],
    ) -> QueryExecutionOutcome[ResponseT]:
        started_at = time.perf_counter()
        pii_applied = bool(spec.pii_columns)

        try:
            rows = await self.trino.execute(spec.statement)
            missing_mappings: tuple[MissingPiiMapping, ...] = ()
            if pii_applied:
                rows, missing = await self.pii_mapper.map_pii_fields(
                    rows=rows,
                    spec=spec,
                )
                missing_mappings = tuple(missing)

            response = response_factory(rows, missing_mappings)
        except asyncio.CancelledError:
            logger.warning(
                "query_execution_completed route_name=%s status=cancelled "
                "duration_ms=%.3f pii_applied=%s",
                spec.route_name,
                _elapsed_ms(started_at),
                _log_bool(pii_applied),
            )
            raise
        except Exception as exc:
            logger.error(
                "query_execution_completed route_name=%s status=failed "
                "duration_ms=%.3f error_type=%s pii_applied=%s",
                spec.route_name,
                _elapsed_ms(started_at),
                type(exc).__name__,
                _log_bool(pii_applied),
            )
            raise

        logger.info(
            "query_execution_completed route_name=%s status=success "
            "duration_ms=%.3f response_type=%s row_count=%d "
            "pii_applied=%s missing_mapping_count=%d",
            spec.route_name,
            _elapsed_ms(started_at),
            type(response).__name__,
            len(rows),
            _log_bool(pii_applied),
            len(missing_mappings),
        )
        return QueryExecutionOutcome(
            response=response,
            missing_mappings=missing_mappings,
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


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def _log_bool(value: bool) -> str:
    return str(value).lower()
