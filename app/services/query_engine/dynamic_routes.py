from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import QueryParams

from app.core.exceptions import ConflictError, NotFoundError
from app.infrastructure.database.client import PostgresClient
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.models.dynamic_route import (
    DynamicRoute,
    DynamicRouteDatabaseType,
    DynamicRouteResponseType,
)
from app.models.user import User
from app.repositories.interfaces.dynamic_route import DynamicRouteRepository
from app.schemas.common import (
    DataRowsResponse,
    MissingPiiMapping,
    PaginatedResponse,
    PaginationMeta,
)
from app.schemas.dynamic_route import DynamicRouteWriteRequest
from app.services.query_engine.dynamic_parameters import (
    DynamicParameterDefinition,
    DynamicParameterError,
    build_bound_statement,
    cast_parameter_values,
    validate_parameter_contract,
)
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.query_engine.pii_rules import (
    PiiColumnRule,
    QuerySpec,
    transform_by_token_length,
)
from app.services.query_engine.sql_safety import (
    DynamicSqlError,
    SqlSafetyValidator,
)


class DynamicRouteService:
    """Manage persisted routes and execute only revalidated canonical SQL."""

    def __init__(
        self,
        *,
        routes: DynamicRouteRepository,
        uow: UnitOfWork,
        trino: TrinoClient,
        postgres: PostgresClient | None = None,
        pii_mapper: PiiMapper | None = None,
        sql_validator: SqlSafetyValidator,
    ) -> None:
        self.routes = routes
        self.uow = uow
        self.trino = trino
        self.postgres = postgres
        self.pii_mapper = pii_mapper
        self.sql_validator = sql_validator

    async def create_route(
        self,
        *,
        payload: DynamicRouteWriteRequest,
        actor: User,
    ) -> DynamicRoute:
        validated = self.sql_validator.validate(
            payload.sql,
            dialect=payload.db_type.value,
        )
        validate_parameter_contract(validated.parameter_names, payload.params)
        existing = await self.routes.get_by_route(
            prefix=payload.prefix,
            path=payload.path,
        )
        if existing is not None:
            raise ConflictError(
                "Dynamic route already exists",
                code="dynamic_route_exists",
            )

        try:
            await self._run_lab_test_if_requested(
                payload=payload,
                canonical_sql=validated.canonical_sql,
            )
            route = DynamicRoute(
                prefix=payload.prefix,
                path=payload.path,
                description=payload.description,
                original_sql=payload.sql,
                canonical_sql=validated.canonical_sql,
                parameter_definitions=_serialize_definitions(payload.params),
                db_type=payload.db_type,
                pii_type=payload.pii_type,
                response_type=payload.response_type,
                created_by=actor.id,
                updated_by=actor.id,
            )
            created = await self.routes.create(route)
            await self.uow.commit()
            return created
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                "Dynamic route already exists",
                code="dynamic_route_exists",
            ) from exc
        except Exception:
            await self.uow.rollback()
            raise

    async def list_routes(self) -> list[DynamicRoute]:
        return await self.routes.list_all()

    async def get_route(self, route_id: UUID) -> DynamicRoute:
        route = await self.routes.get_by_id(route_id)
        if route is None:
            raise NotFoundError("Dynamic route")
        return route

    async def update_route(
        self,
        *,
        route_id: UUID,
        payload: DynamicRouteWriteRequest,
        actor: User,
    ) -> DynamicRoute:
        route = await self.get_route(route_id)
        validated = self.sql_validator.validate(
            payload.sql,
            dialect=payload.db_type.value,
        )
        validate_parameter_contract(validated.parameter_names, payload.params)
        collision = await self.routes.get_by_route(
            prefix=payload.prefix,
            path=payload.path,
        )
        if collision is not None and collision.id != route.id:
            raise ConflictError(
                "Dynamic route already exists",
                code="dynamic_route_exists",
            )

        try:
            await self._run_lab_test_if_requested(
                payload=payload,
                canonical_sql=validated.canonical_sql,
            )
            route.prefix = payload.prefix
            route.path = payload.path
            route.description = payload.description
            route.original_sql = payload.sql
            route.canonical_sql = validated.canonical_sql
            route.parameter_definitions = _serialize_definitions(payload.params)
            route.db_type = payload.db_type
            route.pii_type = payload.pii_type
            route.response_type = payload.response_type
            route.updated_by = actor.id
            updated = await self.routes.update(route)
            await self.uow.commit()
            return updated
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                "Dynamic route already exists",
                code="dynamic_route_exists",
            ) from exc
        except Exception:
            await self.uow.rollback()
            raise

    async def delete_route(self, route_id: UUID) -> DynamicRoute:
        route = await self.get_route(route_id)
        try:
            await self.routes.delete(route)
            await self.uow.commit()
            return route
        except Exception:
            await self.uow.rollback()
            raise

    async def execute_route(
        self,
        *,
        prefix: str,
        path: str,
        raw_params: QueryParams,
    ) -> DataRowsResponse | PaginatedResponse[dict[str, Any]]:
        route = await self.routes.get_by_route(prefix=prefix, path=path)
        if route is None:
            raise NotFoundError("Dynamic route")

        validated = self.sql_validator.validate(
            route.canonical_sql,
            dialect=route.db_type.value,
        )
        definitions = _deserialize_definitions(route.parameter_definitions)
        validate_parameter_contract(validated.parameter_names, definitions)
        query_params, page, page_size = _extract_pagination(
            raw_params,
            response_type=route.response_type,
        )
        parameters = cast_parameter_values(definitions, query_params)
        statement = build_bound_statement(validated.canonical_sql, definitions)
        client = self._client_for(route.db_type)

        if route.response_type is DynamicRouteResponseType.paginated:
            assert page is not None and page_size is not None
            count_sql = (
                "SELECT COUNT(*) AS total FROM "  # noqa: S608
                f"({validated.canonical_sql}) AS dynamic_route_count"
            )
            count_statement = build_bound_statement(
                count_sql,
                definitions,
            )
            count_rows = await client.execute(count_statement, parameters)
            total = _extract_total(count_rows)
            paginated_sql = (
                "SELECT * FROM "  # noqa: S608
                f"({validated.canonical_sql}) AS dynamic_route_data "
                "LIMIT :__dynamic_page_size OFFSET :__dynamic_offset"
            )
            paginated_statement = build_bound_statement(
                paginated_sql,
                definitions,
            )
            paginated_parameters = {
                **parameters,
                "__dynamic_page_size": page_size,
                "__dynamic_offset": (page - 1) * page_size,
            }
            rows = await client.execute(
                paginated_statement,
                paginated_parameters,
            )
            rows, missing_mappings = await self._map_pii(route, rows)
            total_pages = (total + page_size - 1) // page_size
            return PaginatedResponse[dict[str, Any]](
                data=rows,
                pagination=PaginationMeta(
                    total=total,
                    page=page,
                    page_size=page_size,
                    total_pages=total_pages,
                ),
                missing_mappings=missing_mappings,
            )

        rows = await client.execute(statement, parameters)
        rows, missing_mappings = await self._map_pii(route, rows)
        return DataRowsResponse(
            rows=rows,
            missing_mappings=missing_mappings,
        )

    async def _run_lab_test_if_requested(
        self,
        *,
        payload: DynamicRouteWriteRequest,
        canonical_sql: str,
    ) -> None:
        if not payload.lab_test:
            return
        parameters = cast_parameter_values(payload.params, payload.lab_test_params)
        statement = build_bound_statement(canonical_sql, payload.params)
        await self._client_for(payload.db_type).execute(statement, parameters)

    def _client_for(
        self,
        db_type: DynamicRouteDatabaseType,
    ) -> TrinoClient | PostgresClient:
        if db_type is DynamicRouteDatabaseType.trino:
            return self.trino
        if self.postgres is None:
            raise RuntimeError("PostgreSQL client is not configured")
        return self.postgres

    async def _map_pii(
        self,
        route: DynamicRoute,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[MissingPiiMapping]]:
        if route.pii_type is None:
            return rows, []
        if self.pii_mapper is None:
            raise RuntimeError("PII mapper is not configured")
        column_name = route.pii_type.value
        return await self.pii_mapper.map_pii_fields(
            rows=rows,
            spec=QuerySpec(
                route_name=route.api_path,
                statement=route.canonical_sql,
                column_pii_rules={
                    column_name: PiiColumnRule(
                        transformer=transform_by_token_length,
                    )
                },
            ),
        )


def _serialize_definitions(
    definitions: Mapping[str, DynamicParameterDefinition],
) -> dict[str, Any]:
    return {
        name: definition.model_dump(mode="json")
        for name, definition in definitions.items()
    }


def _deserialize_definitions(
    values: Mapping[str, Any],
) -> dict[str, DynamicParameterDefinition]:
    try:
        return {
            name: DynamicParameterDefinition.model_validate(definition)
            for name, definition in values.items()
        }
    except (TypeError, ValidationError) as exc:
        raise DynamicSqlError(
            "dynamic_sql_invalid_parameter_contract",
            "Stored parameter contract is invalid",
        ) from exc


def _extract_pagination(
    raw_params: QueryParams,
    *,
    response_type: DynamicRouteResponseType,
) -> tuple[QueryParams, int | None, int | None]:
    if response_type is DynamicRouteResponseType.data:
        return raw_params, None, None

    page = _parse_pagination_value(raw_params, "page", default=1, maximum=None)
    page_size = _parse_pagination_value(
        raw_params,
        "page_size",
        default=100,
        maximum=1000,
    )
    query_params = QueryParams(
        [
            (name, value)
            for name, value in raw_params.multi_items()
            if name not in {"page", "page_size"}
        ]
    )
    return query_params, page, page_size


def _parse_pagination_value(
    raw_params: QueryParams,
    name: str,
    *,
    default: int,
    maximum: int | None,
) -> int:
    values = raw_params.getlist(name)
    if not values:
        return default
    try:
        if len(values) != 1 or not values[0].isdigit():
            raise ValueError
        value = int(values[0])
        if value < 1 or (maximum is not None and value > maximum):
            raise ValueError
        return value
    except ValueError as exc:
        raise DynamicParameterError(
            "dynamic_parameter_invalid",
            f"Parameter '{name}' is not a valid pagination value",
            details={"parameter": name},
        ) from exc


def _extract_total(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1:
        raise RuntimeError("Pagination count query returned an invalid result")
    row = rows[0]
    for name, value in row.items():
        if name.casefold() == "total":
            return int(value)
    raise RuntimeError("Pagination count query did not return total")
