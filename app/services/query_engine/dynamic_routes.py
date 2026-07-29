from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import QueryParams

from app.core.exceptions import ConflictError, NotFoundError
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.models.dynamic_route import DynamicRoute
from app.models.user import User
from app.repositories.interfaces.dynamic_route import DynamicRouteRepository
from app.schemas.dynamic_route import DynamicRouteWriteRequest
from app.services.query_engine.dynamic_parameters import (
    DynamicParameterDefinition,
    build_bound_statement,
    cast_parameter_values,
    validate_parameter_contract,
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
        sql_validator: SqlSafetyValidator,
    ) -> None:
        self.routes = routes
        self.uow = uow
        self.trino = trino
        self.sql_validator = sql_validator

    async def create_route(
        self,
        *,
        payload: DynamicRouteWriteRequest,
        actor: User,
    ) -> DynamicRoute:
        validated = self.sql_validator.validate(payload.sql)
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
        validated = self.sql_validator.validate(payload.sql)
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
    ) -> list[dict[str, Any]]:
        route = await self.routes.get_by_route(prefix=prefix, path=path)
        if route is None:
            raise NotFoundError("Dynamic route")

        validated = self.sql_validator.validate(route.canonical_sql)
        definitions = _deserialize_definitions(route.parameter_definitions)
        validate_parameter_contract(validated.parameter_names, definitions)
        parameters = cast_parameter_values(definitions, raw_params)
        statement = build_bound_statement(validated.canonical_sql, definitions)
        return await self.trino.execute(statement, parameters)

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
        await self.trino.execute(statement, parameters)


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
