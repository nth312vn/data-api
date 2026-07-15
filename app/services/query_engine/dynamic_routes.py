from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import MissingPiiMapping
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import (
    PiiColumnRule,
    QuerySpec,
    transform_by_token_length,
)

logger = get_logger(__name__)


@dataclass
class DynamicRouteConfig:
    """Configuration for a dynamically created API route."""

    path: str
    sql_template: str
    path_params: list[str]
    column_pii_rules: dict[str, PiiColumnRule]
    description: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    lab_test_result: list[dict[str, Any]] | None = None


class DynamicRouteRegistry:
    """Thread-safe in-memory registry for dynamic routes.

    All data is stored in memory and will be lost on application restart.
    """

    def __init__(self) -> None:
        self._routes: dict[str, DynamicRouteConfig] = {}
        self._lock = threading.Lock()

    def register(self, config: DynamicRouteConfig) -> None:
        """Register a new dynamic route. Overwrites existing route with same path."""
        with self._lock:
            self._routes[config.path] = config
            logger.info("dynamic_route_registered path=%s", config.path)

    def get(self, path: str) -> DynamicRouteConfig | None:
        """Get a dynamic route config by path."""
        with self._lock:
            return self._routes.get(path)

    def list_all(self) -> list[DynamicRouteConfig]:
        """List all registered dynamic routes."""
        with self._lock:
            return list(self._routes.values())

    def remove(self, path: str) -> bool:
        """Remove a dynamic route. Returns True if it existed."""
        with self._lock:
            if path in self._routes:
                del self._routes[path]
                logger.info("dynamic_route_removed path=%s", path)
                return True
            return False

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._routes)


class DynamicRouteService:
    """Service for creating and executing dynamic API routes."""

    def __init__(
        self,
        *,
        registry: DynamicRouteRegistry,
        trino: TrinoClient,
        pii_mapper: PiiMapper,
    ) -> None:
        self.registry = registry
        self.trino = trino
        self.pii_mapper = pii_mapper

    async def create_route(
        self,
        *,
        path: str,
        sql: str,
        path_params: list[str],
        pii_columns: list[str],
        description: str,
        lab_test: bool = False,
        lab_test_params: dict[str, str] | None = None,
    ) -> DynamicRouteConfig:
        """Create a dynamic route and optionally run a lab test."""
        column_pii_rules = {
            column_name: PiiColumnRule(
                transformer=transform_by_token_length,
            )
            for column_name in pii_columns
        }

        config = DynamicRouteConfig(
            path=path,
            sql_template=sql,
            path_params=path_params,
            column_pii_rules=column_pii_rules,
            description=description,
        )

        # Run lab test if requested
        if lab_test:
            resolved_sql = self._resolve_sql(sql, lab_test_params or {})
            spec = QuerySpec(
                route_name=f"dynamic.{path}",
                statement=resolved_sql,
                column_pii_rules=column_pii_rules,
            )
            rows = await self.trino.execute(spec.statement)
            if column_pii_rules:
                rows, _ = await self.pii_mapper.map_pii_fields(
                    rows=rows,
                    spec=spec,
                )
            config.lab_test_result = rows
            logger.info(
                "dynamic_route_lab_test path=%s rows=%d",
                path,
                len(rows),
            )

        self.registry.register(config)
        return config

    async def execute_route(
        self,
        *,
        path: str,
        params: dict[str, str],
    ) -> tuple[
        list[dict[str, Any]],
        DynamicRouteConfig,
        list[MissingPiiMapping],
    ]:
        """Execute a dynamic route with given parameters."""
        config = self.registry.get(path)
        if config is None:
            raise ValueError(f"Dynamic route not found: {path}")

        resolved_sql = self._resolve_sql(config.sql_template, params)
        spec = QuerySpec(
            route_name=f"dynamic.{path}",
            statement=resolved_sql,
            column_pii_rules=config.column_pii_rules,
        )
        rows = await self.trino.execute(spec.statement)
        missing_mappings: list[MissingPiiMapping] = []
        if config.column_pii_rules:
            rows, missing_mappings = await self.pii_mapper.map_pii_fields(
                rows=rows,
                spec=spec,
            )
        return rows, config, missing_mappings

    def _resolve_sql(
        self,
        sql_template: str,
        params: dict[str, str],
    ) -> str:
        """Replace {param} placeholders in SQL template with actual values.

        Only replaces params that are defined in the template.
        Values are single-quoted for safety.
        """
        resolved = sql_template
        for key, value in params.items():
            # Basic SQL injection prevention: escape single quotes
            safe_value = value.replace("'", "''")
            resolved = resolved.replace("{" + key + "}", f"'{safe_value}'")
        return resolved
