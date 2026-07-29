from fastapi import APIRouter, Depends, Request

from app.dependencies.auth import require_api_permission
from app.dependencies.services import get_dynamic_route_service
from app.models.user import User
from app.schemas.common import DataRowsResponse
from app.services.query_engine.dynamic_routes import DynamicRouteService

router = APIRouter()


@router.get("/{prefix}/{path:path}", response_model=DataRowsResponse)
async def execute_dynamic_route(
    prefix: str,
    path: str,
    request: Request,
    _authorized: User = Depends(require_api_permission),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DataRowsResponse:
    rows = await service.execute_route(
        prefix=prefix,
        path=path,
        raw_params=request.query_params,
    )
    return DataRowsResponse(rows=rows, missing_mappings=[])
