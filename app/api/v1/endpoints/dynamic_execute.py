from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.dependencies.auth import require_api_permission
from app.dependencies.services import (
    get_audit_log_service,
    get_dynamic_route_service,
)
from app.models.user import User
from app.schemas.common import DataRowsResponse, PaginatedResponse
from app.services.audit_log import AuditLogService
from app.services.query_engine.dynamic_routes import DynamicRouteService

router = APIRouter()


DynamicExecutionResponse = DataRowsResponse | PaginatedResponse[dict[str, Any]]


@router.get("/{prefix}/{path:path}", response_model=DynamicExecutionResponse)
async def execute_dynamic_route(
    prefix: str,
    path: str,
    request: Request,
    background_tasks: BackgroundTasks,
    authorized: User = Depends(require_api_permission),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
    audit_logs: AuditLogService = Depends(get_audit_log_service),
) -> DynamicExecutionResponse:
    response = await service.execute_route(
        prefix=prefix,
        path=path,
        raw_params=request.query_params,
    )
    if response.missing_mappings:
        background_tasks.add_task(
            audit_logs.audit_missing_mappings,
            actor=authorized,
            route_name=f"dynamic-route:{prefix}/{path}",
            request_parameters={
                "parameter_names": sorted(set(request.query_params.keys()))
            },
            missing_mappings=response.missing_mappings,
        )
    return response
