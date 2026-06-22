from datetime import date, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.power_bi import get_deeplink_1, router
from app.dependencies.auth import get_current_user
from app.dependencies.services import get_data_query_service
from app.models.user import User, UserRole
from app.schemas.data_query import DataRowsResponse
from app.services.data_query import DataQueryService


class RecordingDataQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    async def power_bi_deeplink_1(self, **arguments: Any) -> DataRowsResponse:
        self.arguments = arguments
        return DataRowsResponse(rows=[], missing_mappings=[])


def test_deeplink_query_defaults_to_yesterday_through_today() -> None:
    service = RecordingDataQueryService()
    user = User(
        id=uuid4(),
        email=None,
        username="power_bi",
        hashed_password="hash",
        role=UserRole.user,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_data_query_service] = lambda: service

    today_before_request = date.today()
    with TestClient(app) as client:
        response = client.get("/deeplink_1")
    today_after_request = date.today()

    assert response.status_code == 200
    assert service.arguments["end_date"] in {
        today_before_request,
        today_after_request,
    }
    assert service.arguments["start_date"] == (
        service.arguments["end_date"] - timedelta(days=1)
    )


@pytest.mark.asyncio
async def test_deeplink_api_defaults_date_range_and_forwards_normalized_filters() -> (
    None
):
    service = RecordingDataQueryService()
    user = User(
        id=uuid4(),
        email=None,
        username="power_bi",
        hashed_password="hash",
        role=UserRole.user,
    )

    await get_deeplink_1(
        start_date=None,
        end_date=None,
        limit=None,
        segmentation=["VCB,ACB"],
        user_agent=["Android,Dalvik"],
        customer_id=["uuid-1,uuid-2"],
        current_user=user,
        service=cast(DataQueryService, service),
    )

    assert service.arguments == {
        "actor": user,
        "start_date": date.today() - timedelta(days=1),
        "end_date": date.today(),
        "limit": None,
        "segmentation_filters": ("VCB", "ACB"),
        "user_agent_filters": ("Android", "Dalvik"),
        "customer_ids": ("uuid-1", "uuid-2"),
    }
