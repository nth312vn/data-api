from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_power_bi_service, get_audit_log_service
from app.models.user import User
from app.schemas.common import DataRowsResponse
from app.schemas.power_bi import PowerBiDeeplinkRequest, default_start_date
from app.services.query_engine import PowerBiDataService
from app.services.audit_log import AuditLogService

router = APIRouter()


@router.get("/deeplink_1", response_model=DataRowsResponse)
async def get_deeplink_1(
    background_tasks: BackgroundTasks,
    start_date: date | None = Query(default_factory=default_start_date),
    end_date: date | None = Query(default_factory=date.today),
    limit: int | None = Query(default=None, ge=1),
    segmentation: list[str] = Query(default_factory=list),
    user_agent: list[str] = Query(default_factory=list),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: PowerBiDataService = Depends(get_power_bi_service),
    audit_logs_service: AuditLogService = Depends(get_audit_log_service),
) -> DataRowsResponse:
    request_data: dict[str, object] = {
        "start_date": (start_date if start_date is not None else default_start_date()),
        "end_date": end_date if end_date is not None else date.today(),
        "limit": limit,
        "segmentation": segmentation,
        "user_agent": user_agent,
        "customer_id": customer_id,
    }
    request = PowerBiDeeplinkRequest.model_validate(request_data)
    response = await service.deeplink_1(
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        segmentation_filters=tuple(request.segmentation),
        user_agent_filters=tuple(request.user_agent),
        customer_ids=tuple(request.customer_id),
    )
    if response.missing_mappings:
        background_tasks.add_task(
            audit_logs_service.audit_missing_mappings,
            actor=current_user,
            route_name="power_bi.deeplink_1",
            missing_mappings=response.missing_mappings,
        )
    return response


@router.get("/deeplink_2", response_model=DataRowsResponse)
async def get_deeplink_2(
    background_tasks: BackgroundTasks,
    start_date: date | None = Query(default_factory=default_start_date),
    end_date: date | None = Query(default_factory=date.today),
    limit: int | None = Query(default=None, ge=1),
    segmentation: list[str] = Query(default_factory=list),
    user_agent: list[str] = Query(default_factory=list),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: PowerBiDataService = Depends(get_power_bi_service),
    audit_logs_service: AuditLogService = Depends(get_audit_log_service),
) -> DataRowsResponse:
    request_data: dict[str, object] = {
        "start_date": (start_date if start_date is not None else default_start_date()),
        "end_date": end_date if end_date is not None else date.today(),
        "limit": limit,
        "segmentation": segmentation,
        "user_agent": user_agent,
        "customer_id": customer_id,
    }
    request = PowerBiDeeplinkRequest.model_validate(request_data)
    response = await service.deeplink_2(
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        segmentation_filters=tuple(request.segmentation),
        user_agent_filters=tuple(request.user_agent),
        customer_ids=tuple(request.customer_id),
    )
    if response.missing_mappings:
        background_tasks.add_task(
            audit_logs_service.audit_missing_mappings,
            actor=current_user,
            route_name="power_bi.deeplink_2",
            missing_mappings=response.missing_mappings,
        )
    return response
