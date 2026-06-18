from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.infrastructure.trino import TrinoColumn
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord
from app.schemas.power_bi import PowerBiDeeplinkRequest
from app.services.data_query import DataQueryService
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


class FakeTrinoClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statement: Any | None = None
        self.sql: str | None = None
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any) -> list[dict[str, Any]]:
        self.statement = statement
        self.sql = str(statement)
        if hasattr(statement, "compile"):
            self.params = statement.compile().params
        return self.rows

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
    ) -> list[TrinoColumn]:
        return []


class FakePiiMappingRepository:
    def __init__(self, mappings: dict[PiiMappingKey, str]) -> None:
        self.mappings = mappings
        self.requested_keys: set[PiiMappingKey] = set()
        self.requests: list[set[PiiMappingKey]] = []

    async def get_many(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, PiiMappingRecord]:
        self.requested_keys = keys
        self.requests.append(keys)
        return {
            key: PiiMappingRecord(
                key=key,
                mapped_value=value,
            )
            for key, value in self.mappings.items()
            if key in keys
        }


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.audit_logs: list[AuditLog] = []

    async def create(self, audit_log: AuditLog) -> AuditLog:
        self.audit_logs.append(audit_log)
        return audit_log


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def make_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        role=UserRole.user,
    )


def test_power_bi_request_normalizes_customer_ids() -> None:
    request = PowerBiDeeplinkRequest(
        customer_id=["VNH001,VNH002", " VNH003 "],
        segmentation=["VCB,ACB"],
        user_agent=["Android,Dalvik"],
    )

    assert request.customer_id == ["VNH001", "VNH002", "VNH003"]
    assert request.segmentation == ["VCB", "ACB"]
    assert request.user_agent == ["Android", "Dalvik"]


def test_power_bi_request_defaults_to_today_without_limit() -> None:
    request = PowerBiDeeplinkRequest()

    assert request.start_date == date.today()
    assert request.end_date == date.today()
    assert request.limit is None


@pytest.mark.asyncio
async def test_query_maps_pii_from_cache_and_database() -> None:
    cached_customer_key = PiiMappingKey("trino", "customer_id", "customer-1")
    db_customer_key = PiiMappingKey("trino", "customer_id", "customer-2")
    cache = InMemoryPiiMappingCache()
    cache.set_many(
        {
            cached_customer_key: "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
        },
    )
    mapping_repo = FakePiiMappingRepository(
        {
            db_customer_key: "adf349fb-bbfc-4102-96a1-65af0b063389",
        },
    )
    audit_repo = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    trino = FakeTrinoClient(
        [
            {"customer_id": "customer-1", "amount": 100},
            {"customer_id": "customer-2", "amount": 200},
        ],
    )
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mappings=mapping_repo,
        audit_logs=audit_repo,
        mapping_cache=cache,
        uow=uow,
    )

    response = await service.list_users(
        actor=make_user(),
        limit=50,
        offset=10,
    )

    assert response.rows == [
        {
            "customer_id": "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
            "amount": 100,
        },
        {
            "customer_id": "adf349fb-bbfc-4102-96a1-65af0b063389",
            "amount": 200,
        },
    ]
    assert response.missing_mappings == []
    assert mapping_repo.requested_keys == {db_customer_key}
    assert audit_repo.audit_logs == []
    assert uow.commits == 0
    assert trino.sql is not None
    assert 'FROM "hive"."default"."users"' in trino.sql
    assert "LIMIT 50" in trino.sql
    assert "OFFSET 10" in trino.sql


@pytest.mark.asyncio
async def test_query_audits_missing_pii_mappings() -> None:
    missing_key = PiiMappingKey("trino", "customer_id", "missing-customer")
    audit_repo = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": "missing-customer"}]),
        pii_mappings=FakePiiMappingRepository({}),
        audit_logs=audit_repo,
        mapping_cache=InMemoryPiiMappingCache(),
        uow=uow,
    )

    response = await service.list_users(
        actor=make_user(),
        limit=100,
        offset=0,
    )

    assert response.rows == [{"customer_id": "missing-customer"}]
    assert [mapping.model_dump() for mapping in response.missing_mappings] == [
        {
            "source_system": missing_key.source_system,
            "pii_type": missing_key.pii_type,
            "token": missing_key.token,
        },
    ]
    assert len(audit_repo.audit_logs) == 1
    assert audit_repo.audit_logs[0].api_route == "data.users"
    assert audit_repo.audit_logs[0].allowed is False
    assert audit_repo.audit_logs[0].error_message == "Missing PII mapping"
    assert audit_repo.audit_logs[0].parameters is not None
    assert audit_repo.audit_logs[0].parameters["missing_mappings"] == [
        {
            "source_system": missing_key.source_system,
            "pii_type": missing_key.pii_type,
            "token": missing_key.token,
        },
    ]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_query_does_not_reload_keys_in_temporary_missing_cache() -> None:
    mapping_repo = FakePiiMappingRepository({})
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": "missing-customer"}]),
        pii_mappings=mapping_repo,
        audit_logs=FakeAuditLogRepository(),
        mapping_cache=InMemoryPiiMappingCache(
            missing_ttl_seconds=60,
        ),
        uow=FakeUnitOfWork(),
    )

    await service.list_users(actor=make_user(), limit=100, offset=0)
    await service.list_users(actor=make_user(), limit=100, offset=0)

    assert mapping_repo.requests == [
        {PiiMappingKey("trino", "customer_id", "missing-customer")}
    ]


@pytest.mark.asyncio
async def test_power_bi_deeplink_1_builds_topup_result_query() -> None:
    trino = FakeTrinoClient(
        [
            {
                "stt": 1,
                "accountid": "VNH001234567890X",
            }
        ],
    )
    account_key = PiiMappingKey("trino", "customer_id", "VNH001234567890")
    mapping_repo = FakePiiMappingRepository(
        {
            account_key: "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
        },
    )
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mappings=mapping_repo,
        audit_logs=FakeAuditLogRepository(),
        mapping_cache=InMemoryPiiMappingCache(),
        uow=FakeUnitOfWork(),
    )

    response = await service.power_bi_deeplink_1(
        actor=make_user(),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=1000,
        customer_ids=("7c37bb4b-0e15-4fb9-b589-f57211ac1679",),
    )

    assert response.rows == [
        {"stt": 1, "accountid": "7c37bb4b-0e15-4fb9-b589-f57211ac1679"}
    ]
    assert response.missing_mappings == []
    assert mapping_repo.requested_keys == {account_key}
    assert trino.sql is not None
    assert "FROM hive.wh_cpm.cpm_event_raw" in trino.sql
    assert "LEFT OUTER JOIN hive.wh_bo_hudi.t_cust_customer" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.key = :key_1" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" not in trino.sql
    assert " LIMIT " in trino.sql
    assert "AS event_time" in trino.sql
    assert "AS bank_name" in trino.sql
    assert trino.params["key_1"] == "topup_result"
    assert trino.params["element_at_3"] == "deeplink"
    assert trino.params["date_1"] == date(2026, 6, 1)
    assert trino.params["date_2"] == date(2026, 6, 2)
    assert trino.params["element_at_5"] == "processing"
    assert trino.params["param_4"] == 1000


@pytest.mark.asyncio
async def test_power_bi_deeplink_2_builds_topup_bank_app_query() -> None:
    trino = FakeTrinoClient(
        [
            {"stt": 1, "accountid": "VNH001234567890X"},
            {"stt": 2, "accountid": "VNH001"},
        ],
    )
    account_key = PiiMappingKey("trino", "customer_id", "VNH001234567890")
    mapping_repo = FakePiiMappingRepository(
        {
            account_key: "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
        },
    )
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mappings=mapping_repo,
        audit_logs=FakeAuditLogRepository(),
        mapping_cache=InMemoryPiiMappingCache(),
        uow=FakeUnitOfWork(),
    )

    response = await service.power_bi_deeplink_2(
        actor=make_user(),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=None,
    )

    assert response.rows == [
        {"stt": 1, "accountid": "7c37bb4b-0e15-4fb9-b589-f57211ac1679"},
        {"stt": 2, "accountid": "VNH001"},
    ]
    assert response.missing_mappings == []
    assert mapping_repo.requested_keys == {account_key}
    assert trino.sql is not None
    assert "hive.wh_cpm.cpm_event_raw.key = :key_1" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" not in trino.sql
    assert trino.params["key_1"] == "topup_bank_app"
    assert trino.params["element_at_3"] == "deeplink"
    assert "processing" not in trino.params.values()
    assert " LIMIT " not in trino.sql


@pytest.mark.asyncio
async def test_power_bi_pushes_non_pii_filters_and_limit_to_trino() -> None:
    first_key = PiiMappingKey("trino", "customer_id", "VNH001234567890")
    first_uuid = "7c37bb4b-0e15-4fb9-b589-f57211ac1679"
    trino = FakeTrinoClient(
        [
            {
                "stt": 1,
                "accountid": "VNH001234567890X",
                "bank_name": "VCB",
            },
        ],
    )
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mappings=FakePiiMappingRepository(
            {
                first_key: first_uuid,
            },
        ),
        audit_logs=FakeAuditLogRepository(),
        mapping_cache=InMemoryPiiMappingCache(),
        uow=FakeUnitOfWork(),
    )

    response = await service.power_bi_deeplink_2(
        actor=make_user(),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=1,
        segmentation_filters=("VCB",),
        user_agent_filters=("android",),
        customer_ids=(first_uuid,),
    )

    assert response.rows == [
        {
            "stt": 1,
            "accountid": first_uuid,
            "bank_name": "VCB",
        }
    ]
    assert response.missing_mappings == []
    assert trino.sql is not None
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" not in trino.sql
    assert "lower(element_at(hive.wh_cpm.cpm_event_raw.segmentation" in trino.sql
    assert "lower(hive.wh_cpm.cpm_event_raw.user_agent) LIKE" in trino.sql
    assert " LIMIT " in trino.sql
    assert trino.params["element_at_4"] == "bank_name"
    assert trino.params["lower_5"] == ["vcb"]
    assert trino.params["lower_6"] == "android"
    assert trino.params["param_4"] == 1
