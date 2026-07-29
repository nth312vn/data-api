from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dynamic_route import DynamicRoute
from app.repositories.sqlalchemy.dynamic_route import SQLAlchemyDynamicRouteRepository


def make_route() -> DynamicRoute:
    now = datetime.now(UTC)
    return DynamicRoute(
        id=uuid4(),
        prefix="power_bi",
        path="customer-sales",
        description="Customer sales",
        original_sql="SELECT * FROM sales WHERE region = :region",
        canonical_sql="SELECT * FROM sales WHERE region = :region",
        parameter_definitions={
            "region": {"type": "string", "required": True, "description": ""}
        },
        created_by=None,
        updated_by=None,
        created_at=now,
        updated_at=now,
    )


def test_dynamic_route_model_has_persistence_and_security_constraints() -> None:
    table = DynamicRoute.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_dynamic_routes_prefix_path" in constraint_names
    assert "ck_dynamic_routes_prefix_lower" in constraint_names
    assert "ck_dynamic_routes_path_not_empty" in constraint_names
    assert "ck_dynamic_routes_path_relative" in constraint_names
    assert "ck_dynamic_routes_path_segments" in constraint_names
    assert {
        "ix_dynamic_routes_prefix",
        "ix_dynamic_routes_created_by",
        "ix_dynamic_routes_updated_at",
    } <= index_names
    assert table.c.parameter_definitions.type.__class__.__name__ == "JSONB"
    assert next(iter(table.c.created_by.foreign_keys)).ondelete == "SET NULL"


def test_dynamic_route_model_omits_retired_fields_and_computes_api_path() -> None:
    route = make_route()

    assert route.api_path == "/power_bi/customer-sales"
    assert "pii_columns" not in DynamicRoute.__table__.c
    assert "lab_test_result" not in DynamicRoute.__table__.c
    assert "status" not in DynamicRoute.__table__.c
    assert "version" not in DynamicRoute.__table__.c
    assert "deleted_at" not in DynamicRoute.__table__.c


class FakeScalarResult:
    def __init__(self, route: DynamicRoute | None) -> None:
        self.route = route

    def scalar_one_or_none(self) -> DynamicRoute | None:
        return self.route


class FakeScalars:
    def __init__(self, routes: list[DynamicRoute]) -> None:
        self.routes = routes

    def all(self) -> list[DynamicRoute]:
        return self.routes


class FakeListResult:
    def __init__(self, routes: list[DynamicRoute]) -> None:
        self.routes = routes

    def scalars(self) -> FakeScalars:
        return FakeScalars(self.routes)


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self.results = list(results or [])
        self.statements: list[Any] = []
        self.added: list[DynamicRoute] = []
        self.deleted: list[DynamicRoute] = []
        self.flush_count = 0
        self.refreshed: list[DynamicRoute] = []

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.results.pop(0)

    def add(self, route: DynamicRoute) -> None:
        self.added.append(route)

    async def flush(self) -> None:
        self.flush_count += 1

    async def refresh(self, route: DynamicRoute) -> None:
        self.refreshed.append(route)

    async def delete(self, route: DynamicRoute) -> None:
        self.deleted.append(route)


@pytest.mark.asyncio
async def test_repository_loads_route_by_exact_prefix_and_path() -> None:
    route = make_route()
    session = FakeSession([FakeScalarResult(route)])
    repository = SQLAlchemyDynamicRouteRepository(
        cast(AsyncSession, session),
    )

    result = await repository.get_by_route(
        prefix="power_bi",
        path="customer-sales",
    )

    assert result is route
    sql = str(session.statements[0])
    assert "dynamic_routes.prefix = :prefix_1" in sql
    assert "dynamic_routes.path = :path_1" in sql


@pytest.mark.asyncio
async def test_repository_lists_routes_in_stable_order() -> None:
    routes = [make_route()]
    session = FakeSession([FakeListResult(routes)])
    repository = SQLAlchemyDynamicRouteRepository(
        cast(AsyncSession, session),
    )

    result = await repository.list_all()

    assert result == routes
    assert "ORDER BY dynamic_routes.prefix, dynamic_routes.path" in str(
        session.statements[0]
    )


@pytest.mark.asyncio
async def test_repository_creates_updates_and_hard_deletes_route() -> None:
    route = make_route()
    session = FakeSession()
    repository = SQLAlchemyDynamicRouteRepository(
        cast(AsyncSession, session),
    )

    created = await repository.create(route)
    updated = await repository.update(route)
    await repository.delete(route)

    assert created is route
    assert updated is route
    assert session.added == [route]
    assert session.refreshed == [route, route]
    assert session.deleted == [route]
    assert session.flush_count == 3


@pytest.mark.asyncio
async def test_repository_loads_route_by_uuid() -> None:
    route = make_route()
    route_id: UUID = route.id
    session = FakeSession([FakeScalarResult(route)])
    repository = SQLAlchemyDynamicRouteRepository(
        cast(AsyncSession, session),
    )

    result = await repository.get_by_id(route_id)

    assert result is route
    assert "dynamic_routes.id = :id_1" in str(session.statements[0])
