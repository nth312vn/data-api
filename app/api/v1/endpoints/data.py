from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_data_query_service
from app.models.user import User
from app.schemas.data_query import DataRowsResponse
from app.services.data_query import DataQueryService

router = APIRouter()


@router.get("/users", response_model=DataRowsResponse)
async def list_users_data(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataRowsResponse:
    return await service.list_users(
        actor=current_user,
        limit=limit,
        offset=offset,
    )
