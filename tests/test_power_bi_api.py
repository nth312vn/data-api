from datetime import date, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.power_bi import get_deeplink_1, router
from app.core.exceptions import register_exception_handlers
from app.dependencies.auth import get_current_user
from app.dependencies.services import get_power_bi_service
from app.models.user import User, UserRole
from app.schemas.common import DataRowsResponse
from app.services.query_engine import PowerBiDataService


class RecordingDataQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    async def deeplink_1(
        self,
        **arguments: Any,
    ) -> DataRowsResponse:
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
    app.dependency_overrides[get_power_bi_service] = lambda: service

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


def test_deeplink_pydantic_validation_error_uses_request_error_format() -> None:
    service = RecordingDataQueryService()
    user = User(
        id=uuid4(),
        email=None,
        username="power_bi",
        hashed_password="hash",
        role=UserRole.user,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_power_bi_service] = lambda: service

    response = TestClient(app).get(
        "/deeplink_1",
        params={"start_date": "2026-06-02", "end_date": "2026-06-01"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Invalid request payload"
    assert body["error"]["details"]["errors"] == [
        {
            "field": "request",
            "message": "Value error, start_date must be before or equal to end_date",
            "type": "value_error",
            "input": {
                "start_date": "2026-06-02",
                "end_date": "2026-06-01",
                "limit": None,
                "segmentation": [],
                "user_agent": [],
                "customer_id": [],
            },
        },
    ]


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

    from fastapi import BackgroundTasks

    from tests.test_data_query_service import FakeAuditLogRepository

    await get_deeplink_1(
        background_tasks=BackgroundTasks(),
        start_date=None,
        end_date=None,
        limit=None,
        segmentation=["VCB,ACB"],
        user_agent=["Android,Dalvik"],
        customer_id=["uuid-1,uuid-2"],
        current_user=user,
        service=cast(PowerBiDataService, service),
        audit_logs_service=FakeAuditLogRepository(),
    )

    assert service.arguments == {
        "start_date": date.today() - timedelta(days=1),
        "end_date": date.today(),
        "limit": None,
        "segmentation_filters": ("VCB", "ACB"),
        "user_agent_filters": ("Android", "Dalvik"),
        "customer_ids": ("uuid-1", "uuid-2"),
    }
