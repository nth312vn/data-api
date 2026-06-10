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
    start_date: date = Query(default=date(2026, 6, 1)),
    end_date: date = Query(default=date(2026, 6, 2)),
    limit: int = Query(default=1000, ge=1, le=10000),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    request = PowerBiDeeplinkRequest(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        customer_id=customer_id,
    )
    return await service.power_bi_deeplink_1(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        customer_ids=tuple(request.customer_id),
    )


@router.get("/deeplink_2", response_model=DataRowsResponse)
async def get_deeplink_2(
    start_date: date = Query(default=date(2026, 6, 1)),
    end_date: date = Query(default=date(2026, 6, 2)),
    limit: int = Query(default=1000, ge=1, le=10000),
    customer_id: list[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    request = PowerBiDeeplinkRequest(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        customer_id=customer_id,
    )
    return await service.power_bi_deeplink_2(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        customer_ids=tuple(request.customer_id),
    )
