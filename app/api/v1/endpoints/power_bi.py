from datetime import date

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_data_query_service
from app.models.user import User
from app.schemas.data_query import DataRowsResponse
from app.schemas.power_bi import PowerBiDeeplinkRequest
from app.services.data_query import DataQueryService

router = APIRouter()


@router.get("/deeplink_1", response_model=DataRowsResponse)
async def get_deeplink_1(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    segmentation: list[str] = Query(default_factory=list),
    user_agent: list[str] = Query(default_factory=list),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    request_data: dict[str, object] = {
        "limit": limit,
        "segmentation": segmentation,
        "user_agent": user_agent,
        "customer_id": customer_id,
    }
    if start_date is not None:
        request_data["start_date"] = start_date
    if end_date is not None:
        request_data["end_date"] = end_date
    request = PowerBiDeeplinkRequest.model_validate(request_data)
    return await service.power_bi_deeplink_1(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        segmentation_filters=tuple(request.segmentation),
        user_agent_filters=tuple(request.user_agent),
        customer_ids=tuple(request.customer_id),
    )


@router.get("/deeplink_2", response_model=DataRowsResponse)
async def get_deeplink_2(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    segmentation: list[str] = Query(default_factory=list),
    user_agent: list[str] = Query(default_factory=list),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    request_data: dict[str, object] = {
        "limit": limit,
        "segmentation": segmentation,
        "user_agent": user_agent,
        "customer_id": customer_id,
    }
    if start_date is not None:
        request_data["start_date"] = start_date
    if end_date is not None:
        request_data["end_date"] = end_date
    request = PowerBiDeeplinkRequest.model_validate(request_data)
    return await service.power_bi_deeplink_2(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        segmentation_filters=tuple(request.segmentation),
        user_agent_filters=tuple(request.user_agent),
        customer_ids=tuple(request.customer_id),
    )
