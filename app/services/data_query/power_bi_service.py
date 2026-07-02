from datetime import date
from typing import Any

from app.models.user import User
from app.schemas.common import DataRowsResponse
from app.services.data_query.power_bi import build_power_bi_deeplink_query
from app.services.data_query.routes import (
    DataRouteSpec,
    PiiFieldMappingRule,
    default_pii_token_mapper,
)
from app.services.data_query.service import BaseDataQueryService


class PowerBiDataService(BaseDataQueryService):
    async def deeplink_1(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int | None,
        segmentation_filters: tuple[str, ...] = (),
        user_agent_filters: tuple[str, ...] = (),
        customer_ids: tuple[str, ...] = (),
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="power_bi.deeplink_1",
            statement=build_power_bi_deeplink_query(
                event_key="topup_result",
                start_date=start_date,
                end_date=end_date,
                segmentation_filters=segmentation_filters,
                user_agent_filters=user_agent_filters,
                limit=limit,
                status="processing",
            ),
            pii_field_rules={
                "accountid": PiiFieldMappingRule(
                    pii_type="accountid",
                    token_mapper=default_pii_token_mapper,
                )
            },
        )
        response = await self._execute_route(spec=spec)
        response.rows = self._filter_mapped_customer_ids(
            rows=response.rows,
            customer_ids=customer_ids,
        )
        return response

    async def deeplink_2(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int | None,
        segmentation_filters: tuple[str, ...] = (),
        user_agent_filters: tuple[str, ...] = (),
        customer_ids: tuple[str, ...] = (),
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="power_bi.deeplink_2",
            statement=build_power_bi_deeplink_query(
                event_key="topup_bank_app",
                start_date=start_date,
                end_date=end_date,
                segmentation_filters=segmentation_filters,
                user_agent_filters=user_agent_filters,
                limit=limit,
            ),
            pii_field_rules={
                "accountid": PiiFieldMappingRule(
                    pii_type="accountid",
                    token_mapper=default_pii_token_mapper,
                )
            },
        )
        response = await self._execute_route(spec=spec)
        response.rows = self._filter_mapped_customer_ids(
            rows=response.rows,
            customer_ids=customer_ids,
        )
        return response

    def _filter_mapped_customer_ids(
        self,
        *,
        rows: list[dict[str, Any]],
        customer_ids: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if not rows or not customer_ids:
            return rows

        customer_ids_lower = {value.casefold() for value in customer_ids}
        filtered_rows = []
        stt = 1
        for row in rows:
            accountid = str(row.get("accountid", ""))
            if accountid.casefold() in customer_ids_lower:
                if "stt" in row:
                    row["stt"] = stt
                    stt += 1
                filtered_rows.append(row)
        
        return filtered_rows
