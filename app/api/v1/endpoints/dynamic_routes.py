from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_audit_log_service, get_dynamic_route_service
from app.models.user import User
from app.schemas.common import DataRowsResponse
from app.schemas.dynamic_route import (
    CreateDynamicRouteRequest,
    DynamicRouteListResponse,
    DynamicRouteResponse,
)
from app.services.audit_log import AuditLogService
from app.services.query_engine.dynamic_routes import (
    DynamicRouteConfig,
    DynamicRouteService,
)

router = APIRouter()


def _config_to_response(config: DynamicRouteConfig) -> DynamicRouteResponse:
    return DynamicRouteResponse(
        path=config.path,
        sql=config.sql_template,
        path_params=config.path_params,
        pii_columns=list(config.column_pii_rules),
        description=config.description,
        created_at=config.created_at,
        lab_test_result=config.lab_test_result,
    )


@router.post(
    "", response_model=DynamicRouteResponse, status_code=status.HTTP_201_CREATED
)
async def create_dynamic_route(
    payload: CreateDynamicRouteRequest,
    current_user: User = Depends(get_current_user),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DynamicRouteResponse:
    """Create a new dynamic API route. Optionally run a lab test."""
    config = await service.create_route(
        path=payload.path,
        sql=payload.sql,
        path_params=payload.path_params,
        pii_columns=payload.pii_columns,
        description=payload.description,
        lab_test=payload.lab_test,
        lab_test_params=payload.lab_test_params,
    )
    return _config_to_response(config)


@router.get("", response_model=DynamicRouteListResponse)
async def list_dynamic_routes(
    current_user: User = Depends(get_current_user),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DynamicRouteListResponse:
    """List all registered dynamic routes."""
    configs = service.registry.list_all()
    return DynamicRouteListResponse(
        routes=[_config_to_response(c) for c in configs],
        total=len(configs),
    )


@router.get("/{path:path}", response_model=DataRowsResponse)
async def execute_dynamic_route(
    path: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
    audit_logs_service: AuditLogService = Depends(get_audit_log_service),
) -> DataRowsResponse:
    """Execute a dynamic route by path. Query parameters are used as SQL params."""
    params = dict(request.query_params)
    try:
        rows, _config, missing_mappings = await service.execute_route(
            path=path,
            params=params,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if missing_mappings:
        background_tasks.add_task(
            audit_logs_service.audit_missing_mappings,
            actor=current_user,
            route_name=f"dynamic.{path}",
            request_parameters=params,
            missing_mappings=missing_mappings,
        )
    return DataRowsResponse(rows=rows, missing_mappings=missing_mappings)


@router.delete("/{path:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dynamic_route(
    path: str,
    current_user: User = Depends(get_current_user),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> None:
    """Delete a dynamic route."""
    if not service.registry.remove(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dynamic route not found: {path}",
        )
