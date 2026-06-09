from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_data_query_service
from app.models.user import User
from app.schemas.data_query import DataRowsResponse
from app.schemas.power_bi import PowerBiDeeplinkRequest
from app.services.data_query import DataQueryService

router = APIRouter()


@router.post("/deeplink_1", response_model=DataRowsResponse)
async def post_deeplink_1(
    request: PowerBiDeeplinkRequest,
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    return await service.power_bi_deeplink_1(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        customer_ids=tuple(request.customer_id),
    )


@router.post("/deeplink_2", response_model=DataRowsResponse)
async def post_deeplink_2(
    request: PowerBiDeeplinkRequest,
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    return await service.power_bi_deeplink_2(
        actor=current_user,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
        customer_ids=tuple(request.customer_id),
    )
