from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_users_data_service, get_audit_log_service
from app.models.user import User
from app.schemas.common import DataRowsResponse
from app.services.data_query import UsersDataService
from app.services.audit_log import AuditLogService

router = APIRouter()


@router.get("/users", response_model=DataRowsResponse)
async def list_users_data(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: UsersDataService = Depends(get_users_data_service),
    audit_logs_service: AuditLogService = Depends(get_audit_log_service),
) -> DataRowsResponse:
    response = await service.list_users(
        limit=limit,
        offset=offset,
    )
    if response.missing_mappings:
        background_tasks.add_task(
            audit_logs_service.audit_missing_mappings,
            actor=current_user,
            route_name="data.users",
            missing_mappings=response.missing_mappings,
        )
    return response
