from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_unit_of_work
from app.dependencies.repositories import get_audit_log_repository
from app.dependencies.services import get_dynamic_route_service
from app.models.dynamic_route import DynamicRoute
from app.models.user import User, UserRole
from app.services.query_engine.sql_safety import DynamicSqlError


class FakeAuditRepository:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def create(self, entry: Any) -> Any:
        self.entries.append(entry)
        return entry


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class RecordingDynamicRouteService:
    def __init__(self, create_error: Exception | None = None) -> None:
        self.route = make_route()
        self.create_error = create_error
        self.created = 0
        self.executions: list[tuple[str, str, Any]] = []

    async def create_route(self, *, payload: Any, actor: User) -> DynamicRoute:
        self.created += 1
        if self.create_error is not None:
            raise self.create_error
        self.route.prefix = payload.prefix
        self.route.path = payload.path
        return self.route

    async def list_routes(self) -> list[DynamicRoute]:
        return [self.route]

    async def get_route(self, route_id: UUID) -> DynamicRoute:
        assert route_id == self.route.id
        return self.route

    async def update_route(
        self,
        *,
        route_id: UUID,
        payload: Any,
        actor: User,
    ) -> DynamicRoute:
        assert route_id == self.route.id
        self.route.path = payload.path
        return self.route

    async def delete_route(self, route_id: UUID) -> DynamicRoute:
        assert route_id == self.route.id
        return self.route

    async def execute_route(
        self,
        *,
        prefix: str,
        path: str,
        raw_params: Any,
    ) -> list[dict[str, Any]]:
        self.executions.append((prefix, path, raw_params))
        return [{"customer_id": "customer-1"}]


def make_route() -> DynamicRoute:
    now = datetime.now(UTC)
    return DynamicRoute(
        id=uuid4(),
        prefix="power_bi",
        path="customer-sales",
        description="Customer sales",
        original_sql="SELECT customer_id FROM sales WHERE region = :region",
        canonical_sql="SELECT customer_id FROM sales WHERE region = :region",
        parameter_definitions={
            "region": {
                "type": "string",
                "required": True,
                "default": None,
                "description": "",
            }
        },
        created_by=None,
        updated_by=None,
        created_at=now,
        updated_at=now,
    )


def make_user(username: str, role: UserRole) -> User:
    return User(
        id=uuid4(),
        email=None,
        username=username,
        hashed_password="hashed",
        role=role,
    )


def make_app(
    *,
    user: User,
    service: RecordingDynamicRouteService,
    service_dependency_calls: list[bool] | None = None,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    audit_repository = FakeAuditRepository()
    uow = FakeUnitOfWork()

    def get_service() -> RecordingDynamicRouteService:
        if service_dependency_calls is not None:
            service_dependency_calls.append(True)
        return service

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_dynamic_route_service] = get_service
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repository
    app.dependency_overrides[get_unit_of_work] = lambda: uow
    app.state.audit_repository = audit_repository
    return app


def route_payload(
    *,
    prefix: str = "power_bi",
    path: str = "customer-sales",
) -> dict[str, Any]:
    return {
        "prefix": prefix,
        "path": path,
        "description": "Customer sales",
        "sql": "SELECT customer_id FROM sales WHERE region = :region",
        "params": {"region": {"type": "string"}},
    }


def test_regular_user_cannot_access_management_api() -> None:
    service = RecordingDynamicRouteService()
    app = make_app(
        user=make_user("dynamic-routes", UserRole.user),
        service=service,
    )

    response = TestClient(app).post(
        "/api/v1/dynamic-routes",
        json=route_payload(),
    )

    assert response.status_code == 403
    assert service.created == 0


def test_admin_can_manage_routes_by_uuid_without_pii_fields() -> None:
    service = RecordingDynamicRouteService()
    app = make_app(
        user=make_user("admin", UserRole.admin),
        service=service,
    )
    client = TestClient(app)

    created = client.post("/api/v1/dynamic-routes", json=route_payload())
    listed = client.get("/api/v1/dynamic-routes")
    fetched = client.get(f"/api/v1/dynamic-routes/{service.route.id}")
    updated = client.put(
        f"/api/v1/dynamic-routes/{service.route.id}",
        json=route_payload(path="monthly-sales"),
    )
    deleted = client.delete(f"/api/v1/dynamic-routes/{service.route.id}")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert deleted.status_code == 204
    assert created.json()["api_path"] == "/power_bi/customer-sales"
    assert "pii_columns" not in created.json()
    assert "lab_test_result" not in created.json()
    management_entries = [
        entry
        for entry in app.state.audit_repository.entries
        if entry.api_route.startswith("dynamic-route:")
    ]
    assert management_entries[0].parameters == {
        "action": "create",
        "route_id": str(service.route.id),
        "prefix": "power_bi",
        "path": "customer-sales",
    }
    assert "SELECT" not in repr(management_entries)


def test_registration_rejects_exact_static_get_collision() -> None:
    service = RecordingDynamicRouteService()
    app = make_app(
        user=make_user("admin", UserRole.admin),
        service=service,
    )

    response = TestClient(app).post(
        "/api/v1/dynamic-routes",
        json=route_payload(path="deeplink_1"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "dynamic_route_path_conflict"
    assert service.created == 0


def test_rejected_sql_policy_is_audited_without_sql_or_values() -> None:
    service = RecordingDynamicRouteService(
        create_error=DynamicSqlError(
            "dynamic_sql_statement_not_allowed",
            "Only SELECT queries are allowed",
        ),
    )
    app = make_app(
        user=make_user("admin", UserRole.admin),
        service=service,
    )

    response = TestClient(app).post(
        "/api/v1/dynamic-routes",
        json=route_payload(),
    )

    assert response.status_code == 422
    entry = app.state.audit_repository.entries[0]
    assert entry.allowed is False
    assert entry.parameters == {
        "action": "create",
        "route_id": None,
        "prefix": "power_bi",
        "path": "customer-sales",
        "error_code": "dynamic_sql_statement_not_allowed",
    }
    assert "SELECT" not in repr(entry.parameters)


def test_matching_prefix_user_executes_dynamic_route_without_pii_mapping() -> None:
    service = RecordingDynamicRouteService()
    app = make_app(
        user=make_user("power_bi", UserRole.user),
        service=service,
    )

    injection_payload = "APAC' OR 1=1 --"
    response = TestClient(app).get(
        "/api/v1/power_bi/customer-sales",
        params={"region": injection_payload},
    )

    assert response.status_code == 200
    assert response.json() == {
        "rows": [{"customer_id": "customer-1"}],
        "missing_mappings": [],
    }
    assert service.executions[0][0:2] == ("power_bi", "customer-sales")
    permission_entry = app.state.audit_repository.entries[0]
    assert permission_entry.parameters == {"parameter_names": ["region"]}
    assert injection_payload not in repr(permission_entry.parameters)


def test_authorization_denial_happens_before_service_repository_dependency() -> None:
    service = RecordingDynamicRouteService()
    dependency_calls: list[bool] = []
    app = make_app(
        user=make_user("power_bi_extra", UserRole.user),
        service=service,
        service_dependency_calls=dependency_calls,
    )

    response = TestClient(app).get(
        "/api/v1/power_bi/customer-sales",
        params={"region": "APAC"},
    )

    assert response.status_code == 403
    assert dependency_calls == []
    assert service.executions == []
