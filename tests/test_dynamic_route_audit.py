from uuid import uuid4

import pytest

from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.services.audit_log import AuditLogService


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    async def create(self, entry: AuditLog) -> AuditLog:
        self.entries.append(entry)
        return entry


class RecordingUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_dynamic_route_audit_contains_only_safe_metadata() -> None:
    repository = RecordingAuditRepository()
    uow = RecordingUnitOfWork()
    service = AuditLogService(audit_logs=repository, uow=uow)
    actor = User(
        id=uuid4(),
        username="admin",
        email=None,
        hashed_password="hashed",
        role=UserRole.admin,
    )
    route_id = uuid4()

    await service.audit_dynamic_route_action(
        actor=actor,
        action="create",
        route_id=route_id,
        prefix="power_bi",
        path="customer-sales",
        allowed=False,
        error_code="dynamic_sql_statement_not_allowed",
    )

    entry = repository.entries[0]
    assert entry.parameters == {
        "action": "create",
        "route_id": str(route_id),
        "prefix": "power_bi",
        "path": "customer-sales",
        "error_code": "dynamic_sql_statement_not_allowed",
    }
    serialized: str = repr(entry.parameters)
    for forbidden_value in (
        "SELECT ",
        "canonical_sql",
        "original_sql",
        "APAC' OR 1=1 --",
        "rows",
        "pii",
    ):
        assert forbidden_value not in serialized
    assert entry.allowed is False
    assert entry.error_message == "dynamic_sql_statement_not_allowed"
    assert uow.commits == 1
