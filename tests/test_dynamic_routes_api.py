import pytest
from datetime import date
from uuid import uuid4
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

from app.api.v1.endpoints.dynamic_routes import router
from app.core.exceptions import register_exception_handlers, AuthorizationError
from app.dependencies.auth import get_current_user, require_api_permission, _normalize_route_path, check_api_permission
from app.dependencies.services import get_dynamic_route_service, get_audit_log_service
from app.models.user import User, UserRole
from app.services.query_engine.dynamic_routes import (
    DynamicRouteRegistry,
    DynamicRouteService,
    SqlParamSpec,
    PiiColumnRuleConfig,
    PiiTransformRule,
)
from app.services.query_engine.pii_mapper import PiiMapper
from app.services.account_map_in_memory import AccountMapInMemory
from app.repositories.interfaces.pii_mapping import PiiMappingRecord

class FakeTrinoClient:
    def __init__(self, result_rows: list[dict]):
        self.result_rows = result_rows
        self.last_sql = None
        self.last_params = None

    async def execute(self, statement, parameters=None):
        self.last_sql = str(statement)
        self.last_params = parameters
        return self.result_rows

class FakeAuditLogService:
    async def audit_missing_mappings(self, *args, **kwargs):
        pass

@pytest.fixture
def pii_cache():
    cache = AccountMapInMemory()
    # Add a mock account map record: 32 chars token mapping to resolved-uuid
    cache.add_record(PiiMappingRecord(token="m" * 32, mapped_value="resolved-uuid"))
    # Add a record for custom rules test
    cache.add_record(PiiMappingRecord(token="a" * 10, mapped_value="custom-val"))
    return cache

@pytest.fixture
def trino_client():
    return FakeTrinoClient([
        {"accountid": "m" * 32, "amount": 100, "code": "a" * 10 + "suffix"},
        {"accountid": "other_unmapped", "amount": 200, "code": "short"},
    ])

@pytest.fixture
def dynamic_service(pii_cache, trino_client):
    registry = DynamicRouteRegistry()
    pii_mapper = PiiMapper(mapping_cache=pii_cache)
    return DynamicRouteService(registry=registry, trino=trino_client, pii_mapper=pii_mapper)

@pytest.mark.asyncio
async def test_dynamic_route_creation_validation(dynamic_service):
    # Missing SQL parameters vs declared params check
    with pytest.raises(ValueError, match="SQL parameters do not match declared params"):
        await dynamic_service.create_route(
            path="power_bi/test",
            sql="SELECT * FROM table WHERE id = :id",
            params={}, # id is not declared!
            pii_rules={},
            description="test",
        )

@pytest.mark.asyncio
async def test_execute_route_parameter_casting_and_binding(dynamic_service, trino_client):
    # Create route with various typed parameters
    await dynamic_service.create_route(
        path="power_bi/sales",
        sql="SELECT * FROM sales WHERE min_date >= :start AND max_val <= :max_val AND role IN :roles AND is_active = :active",
        params={
            "start": SqlParamSpec(type="date"),
            "max_val": SqlParamSpec(type="float"),
            "roles": SqlParamSpec(type="string_list"),
            "active": SqlParamSpec(type="boolean"),
        },
        pii_rules={},
        description="sales report",
    )

    # Execute route
    rows, config, missing = await dynamic_service.execute_route(
        path="power_bi/sales",
        params={
            "start": "2026-07-01",
            "max_val": "150.5",
            "roles": "admin, manager",
            "active": "true",
        }
    )

    assert trino_client.last_params["start"] == date(2026, 7, 1)
    assert trino_client.last_params["max_val"] == 150.5
    assert trino_client.last_params["roles"] == ["admin", "manager"]
    assert trino_client.last_params["active"] is True

@pytest.mark.asyncio
async def test_execute_route_pii_rules_mapping(dynamic_service):
    # Create route with preset token_length rule and custom PiiTransformRule rules
    await dynamic_service.create_route(
        path="power_bi/customers",
        sql="SELECT accountid, amount, code FROM customers WHERE status = :status",
        params={
            "status": SqlParamSpec(type="string")
        },
        pii_rules={
            "accountid": PiiColumnRuleConfig(preset="token_length"),
            "code": PiiColumnRuleConfig(custom_rules=[
                # Test custom rule: when min length is 10, treat the last 6 chars as suffix ("suffix"), extract "a" * 10
                PiiTransformRule(
                    when_min_length=10,
                    token_slice=[0, 10],
                    suffix_slice=[10, None]
                )
            ])
        },
        description="test",
    )

    rows, config, missing = await dynamic_service.execute_route(
        path="power_bi/customers",
        params={"status": "active"}
    )

    # The first row should map:
    # "accountid": "m"*32 -> "resolved-uuid"
    # "code": "a"*10 + "suffix" -> "custom-val" + "suffix" -> "custom-valsuffix"
    assert rows[0]["accountid"] == "resolved-uuid"
    assert rows[0]["code"] == "custom-valsuffix"

    # The second row:
    # "accountid": "other_unmapped" -> not mapped -> None
    # "code": "short" -> len=5 <= 10 -> not matching custom rule -> None
    assert rows[1]["accountid"] is None
    assert rows[1]["code"] is None

    # Check missing mappings
    assert len(missing) == 2
    assert {m.column_name for m in missing} == {"accountid", "code"}

@pytest.mark.asyncio
async def test_endpoint_authorization_and_execution(dynamic_service):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(
        router,
        prefix="/dynamic-routes",
        dependencies=[Depends(require_api_permission)]
    )

    # Dependency overrides
    user_power_bi = User(
        id=uuid4(),
        email=None,
        username="power_bi",
        hashed_password="hash",
        role=UserRole.user
    )

    async def mock_require_api_permission(
        request: Request,
        current_user: User = Depends(get_current_user),
    ):
        route_path = _normalize_route_path(request.url.path, api_v1_prefix="")
        allowed, error = await check_api_permission(user=current_user, route_path=route_path)
        if not allowed:
            raise AuthorizationError(error or "API permission denied")
        return current_user

    app.dependency_overrides[get_current_user] = lambda: user_power_bi
    app.dependency_overrides[get_dynamic_route_service] = lambda: dynamic_service
    app.dependency_overrides[get_audit_log_service] = lambda: FakeAuditLogService()
    app.dependency_overrides[require_api_permission] = mock_require_api_permission

    # Pre-register a route under power_bi namespace
    await dynamic_service.create_route(
        path="power_bi/report1",
        sql="SELECT * FROM table WHERE value = :value",
        params={"value": SqlParamSpec(type="string")},
        pii_rules={},
        description="test report",
    )

    # Pre-register a route under other user namespace
    await dynamic_service.create_route(
        path="other_user/report1",
        sql="SELECT * FROM table WHERE value = :value",
        params={"value": SqlParamSpec(type="string")},
        pii_rules={},
        description="test report other",
    )

    client = TestClient(app)

    # 1. Calling dynamic route prefix matching user should succeed
    response = client.get("/dynamic-routes/power_bi/report1", params={"value": "xyz"})
    assert response.status_code == 200

    # 2. Calling dynamic route prefix not matching user should get 403 Forbidden
    response = client.get("/dynamic-routes/other_user/report1", params={"value": "xyz"})
    assert response.status_code == 403
