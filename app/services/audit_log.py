from typing import Any
from uuid import UUID

from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.schemas.common import MissingPiiMapping


class AuditLogService:
    def __init__(
        self,
        *,
        audit_logs: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self.audit_logs = audit_logs
        self.uow = uow

    async def audit_missing_mappings(
        self,
        *,
        actor: User,
        route_name: str,
        request_parameters: dict[str, Any],
        missing_mappings: list[MissingPiiMapping],
    ) -> None:
        parameters = dict(request_parameters)
        parameters["missing_mappings"] = [
            mapping.model_dump() for mapping in missing_mappings
        ]
        await self.audit_logs.create(
            AuditLog(
                user_id=actor.id,
                username=actor.username,
                api_route=route_name,
                parameters=parameters,
                allowed=False,
                error_message="Missing PII mapping",
            ),
        )
        await self.uow.commit()

    async def audit_dynamic_route_action(
        self,
        *,
        actor: User,
        action: str,
        route_id: UUID | None,
        prefix: str,
        path: str,
        allowed: bool,
        error_code: str | None = None,
    ) -> None:
        parameters: dict[str, Any] = {
            "action": action,
            "route_id": str(route_id) if route_id is not None else None,
            "prefix": prefix,
            "path": path,
        }
        if error_code is not None:
            parameters["error_code"] = error_code
        await self.audit_logs.create(
            AuditLog(
                user_id=actor.id,
                username=actor.username,
                api_route=f"dynamic-route:{prefix}/{path}",
                parameters=parameters,
                allowed=allowed,
                error_message=error_code,
            ),
        )
        await self.uow.commit()
