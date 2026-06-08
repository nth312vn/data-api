from typing import Protocol

from app.models.audit_log import AuditLog


class AuditLogRepository(Protocol):
    async def create(self, audit_log: AuditLog) -> AuditLog: ...
