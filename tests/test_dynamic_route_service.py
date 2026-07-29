from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql import Executable
from starlette.datastructures import QueryParams

from app.core.exceptions import ConflictError, NotFoundError
from app.infrastructure.trino.client import TrinoClient
from app.models.dynamic_route import DynamicRoute
from app.models.user import User, UserRole
from app.repositories.interfaces.dynamic_route import DynamicRouteRepository
from app.schemas.dynamic_route import DynamicRouteWriteRequest
from app.services.query_engine.dynamic_routes import DynamicRouteService
from app.services.query_engine.sql_safety import DynamicSqlError, SqlSafetyValidator


class MemoryRouteRepository:
    def __init__(self) -> None:
        self.routes: dict[UUID, DynamicRoute] = {}

    async def get_by_id(self, route_id: UUID) -> DynamicRoute | None:
        return self.routes.get(route_id)

    async def get_by_route(
        self,
        *,
        prefix: str,
        path: str,
    ) -> DynamicRoute | None:
        return next(
            (
                route
                for route in self.routes.values()
                if route.prefix == prefix and route.path == path
            ),
            None,
        )

    async def list_all(self) -> list[DynamicRoute]:
        return sorted(
            self.routes.values(),
            key=lambda route: (route.prefix, route.path),
        )

    async def create(self, route: DynamicRoute) -> DynamicRoute:
        if route.id is None:
            route.id = uuid4()
        self.routes[route.id] = route
        return route

    async def update(self, route: DynamicRoute) -> DynamicRoute:
        self.routes[route.id] = route
        return route

    async def delete(self, route: DynamicRoute) -> None:
        del self.routes[route.id]


class RecordingUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class RecordingTrino:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.executions: list[tuple[str, Mapping[str, object] | None]] = []

    async def execute(
        self,
        statement: str | Executable,
        parameters: Mapping[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        self.executions.append((str(statement), parameters))
        if self.error is not None:
            raise self.error
        return [{"ok": True}]

    async def get_catalogs(self) -> list[str]:
        return []

    async def get_schemas(self, *, catalog: str) -> list[str]:
        return []

    async def get_tables(self, *, catalog: str, schema: str) -> list[str]:
        return []

    async def get_columns(
        self,
        *,
        catalog: str,
        schema: str,
        table: str,
    ) -> list[Any]:
        return []


def make_actor() -> User:
    return User(
        id=uuid4(),
        username="admin",
        email="admin@example.com",
        hashed_password="hashed",
        role=UserRole.admin,
    )


def make_payload(
    *,
    prefix: str = "power_bi",
    path: str = "customer-sales",
    lab_test: bool = False,
) -> DynamicRouteWriteRequest:
    return DynamicRouteWriteRequest(
        prefix=prefix,
        path=path,
        description="Customer sales",
        sql=("SELECT customer_id FROM sales " "WHERE region = :region /* remove me */"),
        params={"region": {"type": "string"}},
        lab_test=lab_test,
        lab_test_params={"region": "APAC"} if lab_test else {},
    )


def make_service(
    repository: MemoryRouteRepository,
    uow: RecordingUnitOfWork,
    trino: RecordingTrino,
) -> DynamicRouteService:
    return DynamicRouteService(
        routes=repository,
        uow=uow,
        trino=trino,
        sql_validator=SqlSafetyValidator(),
    )


@pytest.mark.asyncio
async def test_create_validates_lab_tests_and_persists_canonical_sql() -> None:
    repository = MemoryRouteRepository()
    uow = RecordingUnitOfWork()
    trino = RecordingTrino()
    service = make_service(repository, uow, trino)

    route = await service.create_route(
        payload=make_payload(lab_test=True),
        actor=make_actor(),
    )

    assert route is await repository.get_by_id(route.id)
    assert "remove me" not in route.canonical_sql
    assert route.original_sql.endswith("/* remove me */")
    assert route.parameter_definitions["region"]["type"] == "string"
    assert trino.executions == [
        (
            "SELECT customer_id FROM sales WHERE region = :region",
            {"region": "APAC"},
        )
    ]
    assert uow.commits == 1
    assert uow.rollbacks == 0


@pytest.mark.asyncio
async def test_create_rolls_back_and_stores_nothing_when_lab_test_fails() -> None:
    repository = MemoryRouteRepository()
    uow = RecordingUnitOfWork()
    trino = RecordingTrino(RuntimeError("Trino rejected query"))
    service = make_service(repository, uow, trino)

    with pytest.raises(RuntimeError, match="Trino rejected query"):
        await service.create_route(
            payload=make_payload(lab_test=True),
            actor=make_actor(),
        )

    assert repository.routes == {}
    assert uow.commits == 0
    assert uow.rollbacks == 1


@pytest.mark.asyncio
async def test_create_rejects_duplicate_prefix_and_path() -> None:
    repository = MemoryRouteRepository()
    service = make_service(
        repository,
        RecordingUnitOfWork(),
        RecordingTrino(),
    )
    actor = make_actor()
    await service.create_route(payload=make_payload(), actor=actor)

    with pytest.raises(ConflictError) as exc_info:
        await service.create_route(payload=make_payload(), actor=actor)

    assert exc_info.value.code == "dynamic_route_exists"


@pytest.mark.asyncio
async def test_update_replaces_one_row_and_delete_hard_deletes_it() -> None:
    repository = MemoryRouteRepository()
    uow = RecordingUnitOfWork()
    service = make_service(repository, uow, RecordingTrino())
    actor = make_actor()
    route = await service.create_route(payload=make_payload(), actor=actor)
    updated_payload = make_payload(path="monthly-sales")

    updated = await service.update_route(
        route_id=route.id,
        payload=updated_payload,
        actor=actor,
    )

    assert updated.id == route.id
    assert updated.path == "monthly-sales"
    assert updated.updated_by == actor.id
    assert len(repository.routes) == 1

    await service.delete_route(route.id)

    assert repository.routes == {}
    assert uow.commits == 3


@pytest.mark.asyncio
async def test_get_update_and_delete_raise_not_found_for_unknown_uuid() -> None:
    service = make_service(
        MemoryRouteRepository(),
        RecordingUnitOfWork(),
        RecordingTrino(),
    )
    unknown_id = uuid4()

    with pytest.raises(NotFoundError):
        await service.get_route(unknown_id)
    with pytest.raises(NotFoundError):
        await service.update_route(
            route_id=unknown_id,
            payload=make_payload(),
            actor=make_actor(),
        )
    with pytest.raises(NotFoundError):
        await service.delete_route(unknown_id)


@pytest.mark.asyncio
async def test_execute_revalidates_database_sql_and_binds_injection_payload() -> None:
    repository = MemoryRouteRepository()
    trino = RecordingTrino()
    service = make_service(repository, RecordingUnitOfWork(), trino)
    route = await service.create_route(payload=make_payload(), actor=make_actor())
    payload = "APAC' OR 1=1 --"

    rows = await service.execute_route(
        prefix="power_bi",
        path="customer-sales",
        raw_params=QueryParams({"region": payload}),
    )

    assert rows == [{"ok": True}]
    statement, parameters = trino.executions[0]
    assert payload not in statement
    assert parameters == {"region": payload}

    route.canonical_sql = "SELECT 1; DELETE FROM sales"
    with pytest.raises(DynamicSqlError):
        await service.execute_route(
            prefix="power_bi",
            path="customer-sales",
            raw_params=QueryParams({"region": "APAC"}),
        )


@pytest.mark.asyncio
async def test_execute_uses_repository_as_source_of_truth_across_services() -> None:
    repository = MemoryRouteRepository()
    creator = make_service(
        repository,
        RecordingUnitOfWork(),
        RecordingTrino(),
    )
    await creator.create_route(payload=make_payload(), actor=make_actor())
    restarted_service = make_service(
        repository,
        RecordingUnitOfWork(),
        RecordingTrino(),
    )

    rows = await restarted_service.execute_route(
        prefix="power_bi",
        path="customer-sales",
        raw_params=QueryParams({"region": "APAC"}),
    )

    assert rows == [{"ok": True}]


def test_service_constructor_requires_repository_not_registry_or_pii_mapper() -> None:
    repository: DynamicRouteRepository = MemoryRouteRepository()
    trino: TrinoClient = RecordingTrino()

    service = DynamicRouteService(
        routes=repository,
        uow=RecordingUnitOfWork(),
        trino=trino,
        sql_validator=SqlSafetyValidator(),
    )

    assert service.routes is repository
