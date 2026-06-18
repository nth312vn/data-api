from datetime import date
from typing import Any, cast
from uuid import uuid4

import pytest

from app.api.v1.endpoints.power_bi import get_deeplink_1
from app.models.user import User, UserRole
from app.schemas.data_query import DataRowsResponse
from app.services.data_query import DataQueryService


class RecordingDataQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    async def power_bi_deeplink_1(self, **arguments: Any) -> DataRowsResponse:
        self.arguments = arguments
        return DataRowsResponse(rows=[], missing_mappings=[])


@pytest.mark.asyncio
async def test_deeplink_api_defaults_dates_and_forwards_normalized_filters() -> None:
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
        "start_date": date.today(),
        "end_date": date.today(),
        "limit": None,
        "segmentation_filters": ("VCB", "ACB"),
        "user_agent_filters": ("Android", "Dalvik"),
        "customer_ids": ("uuid-1", "uuid-2"),
    }
