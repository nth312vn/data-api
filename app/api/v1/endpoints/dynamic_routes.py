from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError
from app.dependencies.auth import require_roles
from app.dependencies.services import (
    get_audit_log_service,
    get_dynamic_route_service,
)
from app.models.dynamic_route import DynamicRoute
from app.models.user import User, UserRole
from app.schemas.dynamic_route import (
    DynamicRouteListResponse,
    DynamicRouteResponse,
    DynamicRouteWriteRequest,
)
from app.services.audit_log import AuditLogService
from app.services.query_engine.dynamic_parameters import (
    DynamicParameterDefinition,
)
from app.services.query_engine.dynamic_routes import DynamicRouteService
from app.services.query_engine.sql_safety import DynamicSqlError

router = APIRouter()


@router.post(
    "",
    response_model=DynamicRouteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dynamic_route(
    payload: DynamicRouteWriteRequest,
    request: Request,
    admin: User = Depends(require_roles(UserRole.admin)),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
    audit_logs: AuditLogService = Depends(get_audit_log_service),
    settings: Settings = Depends(get_settings),
) -> DynamicRouteResponse:
    _reject_static_get_collision(
        request=request,
        settings=settings,
        prefix=payload.prefix,
        path=payload.path,
    )
    try:
        route = await service.create_route(payload=payload, actor=admin)
    except DynamicSqlError as exc:
        await audit_logs.audit_dynamic_route_action(
            actor=admin,
            action="create",
            route_id=None,
            prefix=payload.prefix,
            path=payload.path,
            allowed=False,
            error_code=exc.code,
        )
        raise
    await audit_logs.audit_dynamic_route_action(
        actor=admin,
        action="create",
        route_id=route.id,
        prefix=route.prefix,
        path=route.path,
        allowed=True,
    )
    return _route_to_response(route)


@router.get("", response_model=DynamicRouteListResponse)
async def list_dynamic_routes(
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DynamicRouteListResponse:
    routes = await service.list_routes()
    return DynamicRouteListResponse(
        routes=[_route_to_response(route) for route in routes],
        total=len(routes),
    )


@router.get("/{route_id}", response_model=DynamicRouteResponse)
async def get_dynamic_route(
    route_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DynamicRouteResponse:
    return _route_to_response(await service.get_route(route_id))


@router.put("/{route_id}", response_model=DynamicRouteResponse)
async def update_dynamic_route(
    route_id: UUID,
    payload: DynamicRouteWriteRequest,
    request: Request,
    admin: User = Depends(require_roles(UserRole.admin)),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
    audit_logs: AuditLogService = Depends(get_audit_log_service),
    settings: Settings = Depends(get_settings),
) -> DynamicRouteResponse:
    _reject_static_get_collision(
        request=request,
        settings=settings,
        prefix=payload.prefix,
        path=payload.path,
    )
    try:
        route = await service.update_route(
            route_id=route_id,
            payload=payload,
            actor=admin,
        )
    except DynamicSqlError as exc:
        await audit_logs.audit_dynamic_route_action(
            actor=admin,
            action="update",
            route_id=route_id,
            prefix=payload.prefix,
            path=payload.path,
            allowed=False,
            error_code=exc.code,
        )
        raise
    await audit_logs.audit_dynamic_route_action(
        actor=admin,
        action="update",
        route_id=route.id,
        prefix=route.prefix,
        path=route.path,
        allowed=True,
    )
    return _route_to_response(route)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dynamic_route(
    route_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
    audit_logs: AuditLogService = Depends(get_audit_log_service),
) -> Response:
    route = await service.delete_route(route_id)
    await audit_logs.audit_dynamic_route_action(
        actor=_admin,
        action="delete",
        route_id=route.id,
        prefix=route.prefix,
        path=route.path,
        allowed=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _route_to_response(route: DynamicRoute) -> DynamicRouteResponse:
    return DynamicRouteResponse(
        id=route.id,
        prefix=route.prefix,
        path=route.path,
        description=route.description,
        sql=route.original_sql,
        canonical_sql=route.canonical_sql,
        params={
            name: DynamicParameterDefinition.model_validate(definition)
            for name, definition in route.parameter_definitions.items()
        },
        db_type=route.db_type,
        pii_type=route.pii_type,
        response_type=route.response_type,
        created_by=route.created_by,
        updated_by=route.updated_by,
        created_at=route.created_at,
        updated_at=route.updated_at,
    )


def _reject_static_get_collision(
    *,
    request: Request,
    settings: Settings,
    prefix: str,
    path: str,
) -> None:
    api_prefix = settings.api_v1_prefix.rstrip("/")
    effective_path = f"{api_prefix}/{prefix}/{path}"
    for registered_route in request.app.routes:
        route_path = getattr(registered_route, "path", None)
        methods = getattr(registered_route, "methods", None)
        if (
            route_path == effective_path
            and methods is not None
            and "GET" in methods
            and "{path:path}" not in route_path
        ):
            raise ConflictError(
                "Dynamic route conflicts with a static GET endpoint",
                code="dynamic_route_path_conflict",
            )
