from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.repositories import get_audit_log_repository
from app.dependencies.database import get_unit_of_work
from app.dependencies.services import get_users_data_service
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.schemas.common import DataRowsResponse, MissingPiiMapping
from app.services.data_query import UsersDataService

router = APIRouter()


async def _audit_missing_mappings(
    *,
    audit_logs: AuditLogRepository,
    uow: UnitOfWork,
    actor: User,
    route_name: str,
    missing_mappings: list[MissingPiiMapping],
) -> None:
    await audit_logs.create(
        AuditLog(
            user_id=actor.id,
            username=actor.username,
            api_route=route_name,
            parameters={
                "missing_mappings": [
                    mapping.model_dump() for mapping in missing_mappings
                ],
            },
            allowed=False,
            error_message="Missing PII mapping",
        ),
    )
    await uow.commit()


@router.get("/users", response_model=DataRowsResponse)
async def list_users_data(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: UsersDataService = Depends(get_users_data_service),
    audit_logs: AuditLogRepository = Depends(get_audit_log_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> DataRowsResponse:
    response = await service.list_users(
        limit=limit,
        offset=offset,
    )
    if response.missing_mappings:
        background_tasks.add_task(
            _audit_missing_mappings,
            audit_logs=audit_logs,
            uow=uow,
            actor=current_user,
            route_name="data.users",
            missing_mappings=response.missing_mappings,
        )
    return response
