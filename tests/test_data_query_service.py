from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.infrastructure.trino import TrinoColumn
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord
from app.services.data_query import DataQueryService
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


class FakeTrinoClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.sql: str | None = None

    async def execute(self, sql: str) -> list[dict[str, Any]]:
        self.sql = sql
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

    async def get_many(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, PiiMappingRecord]:
        self.requested_keys = keys
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
        is_active=True,
        role=UserRole.user,
    )


@pytest.mark.asyncio
async def test_query_maps_pii_from_cache_and_database() -> None:
    cached_email_key = PiiMappingKey("trino", "email_token", "tok-1")
    cached_phone_key = PiiMappingKey("trino", "phone_token", "phone-1")
    db_email_key = PiiMappingKey("trino", "email_token", "tok-2")
    db_phone_key = PiiMappingKey("trino", "phone_token", "phone-2")
    cache = InMemoryPiiMappingCache(max_size=10)
    cache.set_many(
        {
            cached_email_key: "user-1@example.com",
            cached_phone_key: "+84900000001",
        },
    )
    mapping_repo = FakePiiMappingRepository(
        {
            db_email_key: "user-2@example.com",
            db_phone_key: "+84900000002",
        },
    )
    audit_repo = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    trino = FakeTrinoClient(
        [
            {"email_token": "tok-1", "phone_token": "phone-1", "amount": 100},
            {"email_token": "tok-2", "phone_token": "phone-2", "amount": 200},
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
            "email_token": "user-1@example.com",
            "phone_token": "+84900000001",
            "amount": 100,
        },
        {
            "email_token": "user-2@example.com",
            "phone_token": "+84900000002",
            "amount": 200,
        },
    ]
    assert response.missing_mappings == []
    assert mapping_repo.requested_keys == {db_email_key, db_phone_key}
    assert audit_repo.audit_logs == []
    assert uow.commits == 0
    assert trino.sql is not None
    assert 'FROM "hive"."default"."users"' in trino.sql
    assert "LIMIT 50" in trino.sql
    assert "OFFSET 10" in trino.sql


@pytest.mark.asyncio
async def test_query_audits_missing_pii_mappings() -> None:
    missing_key = PiiMappingKey("trino", "email_token", "missing-token")
    audit_repo = FakeAuditLogRepository()
    uow = FakeUnitOfWork()
    service = DataQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"email_token": "missing-token"}]),
        pii_mappings=FakePiiMappingRepository({}),
        audit_logs=audit_repo,
        mapping_cache=InMemoryPiiMappingCache(max_size=10),
        uow=uow,
    )

    response = await service.list_users(
        actor=make_user(),
        limit=100,
        offset=0,
    )

    assert response.rows == [{"email_token": "missing-token"}]
    assert [mapping.model_dump() for mapping in response.missing_mappings] == [
        {
            "source_system": missing_key.source_system,
            "pii_type": missing_key.pii_type,
            "token": missing_key.token,
        },
    ]
    assert len(audit_repo.audit_logs) == 1
    assert audit_repo.audit_logs[0].event_type == "pii_mapping_missing"
    assert audit_repo.audit_logs[0].payload["route"] == "data.users"
    assert audit_repo.audit_logs[0].payload["missing_mappings"] == [
        {
            "source_system": missing_key.source_system,
            "pii_type": missing_key.pii_type,
            "token": missing_key.token,
        },
    ]
    assert uow.commits == 1
