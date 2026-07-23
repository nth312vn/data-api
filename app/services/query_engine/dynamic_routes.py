from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from typing import Any

from app.core.logging import get_logger
from app.infrastructure.trino.client import TrinoClient
from app.schemas.common import MissingPiiMapping
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import (
    PiiColumnRule,
    PiiValueTransformer,
    QuerySpec,
    transform_by_token_length,
    transform_when_exceeds_length,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SqlParamSpec:
    """Specification for a dynamic SQL parameter."""

    type: str
    required: bool = True
    default: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class PiiTransformRule:
    """Custom parameterized PII transformation rule details."""

    when_length: int | None = None
    when_min_length: int | None = None
    token_slice: list[int | None] | None = None
    suffix_slice: list[int | None] | None = None
    strip_last_as_suffix: bool = False


@dataclass(frozen=True, slots=True)
class PiiColumnRuleConfig:
    """PII transformation rule configuration for a column."""

    preset: str | None = None
    custom_rules: list[PiiTransformRule] | None = None


@dataclass
class DynamicRouteConfig:
    """Configuration for a dynamically created API route."""

    path: str
    sql_template: str
    param_specs: dict[str, SqlParamSpec]
    pii_rules_config: dict[str, PiiColumnRuleConfig]
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


PARAM_CASTERS = {
    "string": lambda v: str(v),
    "date": lambda v: date.fromisoformat(v) if isinstance(v, str) else v,
    "integer": lambda v: int(v),
    "float": lambda v: float(v),
    "boolean": lambda v: str(v).lower() in ("true", "1", "t", "yes", "y", "true"),
    "string_list": lambda v: [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v),
}

TRANSFORMER_REGISTRY = {
    "token_length": transform_by_token_length,
    "exceeds_10": partial(transform_when_exceeds_length, min_length=10),
    "exceeds_10_strip": partial(transform_when_exceeds_length, min_length=10, strip_last_character=True),
}


def make_custom_transformer(rules: list[PiiTransformRule]) -> PiiValueTransformer:
    """Build a custom parameterized PII value transformer."""
    def transformer(value: Any, pii_cache: Mapping[str, str]) -> Any:
        if value is None:
            return None
        token_str = str(value)

        for rule in rules:
            if rule.when_length is not None and len(token_str) != rule.when_length:
                continue
            if rule.when_min_length is not None and len(token_str) <= rule.when_min_length:
                continue

            if rule.strip_last_as_suffix:
                actual_token = token_str[:-1]
                suffix = token_str[-1]
            else:
                start, end = 0, None
                if rule.token_slice and len(rule.token_slice) >= 1:
                    start = rule.token_slice[0] or 0
                if rule.token_slice and len(rule.token_slice) >= 2:
                    end = rule.token_slice[1]
                actual_token = token_str[start:end]

                suffix = ""
                if rule.suffix_slice:
                    s_start, s_end = None, None
                    if len(rule.suffix_slice) >= 1:
                        s_start = rule.suffix_slice[0]
                    if len(rule.suffix_slice) >= 2:
                        s_end = rule.suffix_slice[1]
                    suffix = token_str[s_start:s_end]

            mapped = pii_cache.get(actual_token)
            if mapped is not None:
                return mapped + suffix
            return None
        return None
    return transformer


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
        params: dict[str, SqlParamSpec],
        pii_rules: dict[str, PiiColumnRuleConfig],
        description: str,
        lab_test: bool = False,
        lab_test_params: dict[str, str] | None = None,
    ) -> DynamicRouteConfig:
        """Create a dynamic route and optionally run a lab test."""
        # Validate placeholders in SQL vs declared parameters
        used_params = set(re.findall(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)", sql))
        declared_params = set(params.keys())
        if used_params != declared_params:
            raise ValueError(
                f"SQL parameters do not match declared params. SQL placeholders: {used_params}, Declared: {declared_params}"
            )

        # Build column PII rules
        column_pii_rules = {}
        for col_name, rule_config in pii_rules.items():
            if rule_config.preset:
                if rule_config.preset not in TRANSFORMER_REGISTRY:
                    raise ValueError(f"Unknown preset PII transformer: {rule_config.preset}")
                column_pii_rules[col_name] = PiiColumnRule(
                    transformer=TRANSFORMER_REGISTRY[rule_config.preset]
                )
            elif rule_config.custom_rules:
                column_pii_rules[col_name] = PiiColumnRule(
                    transformer=make_custom_transformer(rule_config.custom_rules)
                )

        config = DynamicRouteConfig(
            path=path,
            sql_template=sql,
            param_specs=params,
            pii_rules_config=pii_rules,
            column_pii_rules=column_pii_rules,
            description=description,
        )

        # Run lab test if requested
        if lab_test:
            lab_test_params = lab_test_params or {}
            cast_lab_params = {}
            for param_name, spec in params.items():
                val = lab_test_params.get(param_name)
                if val is None:
                    if spec.required:
                        raise ValueError(f"Missing required parameter for lab test: {param_name}")
                    val = spec.default
                if val is not None:
                    try:
                        cast_lab_params[param_name] = PARAM_CASTERS[spec.type](val)
                    except Exception as exc:
                        raise ValueError(
                            f"Invalid value for lab test parameter '{param_name}': {exc}"
                        ) from exc

            spec = QuerySpec(
                route_name=f"dynamic.{path}",
                statement=sql,
                column_pii_rules=column_pii_rules,
            )
            rows = await self.trino.execute(spec.statement, parameters=cast_lab_params)
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

        # Cast incoming parameters to correct Python types based on spec
        cast_params = {}
        for param_name, spec in config.param_specs.items():
            val = params.get(param_name)
            if val is None:
                if spec.required:
                    raise ValueError(f"Missing required parameter: {param_name}")
                val = spec.default
            if val is not None:
                try:
                    cast_params[param_name] = PARAM_CASTERS[spec.type](val)
                except Exception as exc:
                    raise ValueError(f"Invalid value for parameter '{param_name}': {exc}") from exc

        spec = QuerySpec(
            route_name=f"dynamic.{path}",
            statement=config.sql_template,
            column_pii_rules=config.column_pii_rules,
        )
        rows = await self.trino.execute(spec.statement, parameters=cast_params)
        missing_mappings: list[MissingPiiMapping] = []
        if config.column_pii_rules:
            rows, missing_mappings = await self.pii_mapper.map_pii_fields(
                rows=rows,
                spec=spec,
            )
        return rows, config, missing_mappings
