from datetime import date
from typing import Any

from app.schemas.common import DataRowsResponse, MissingPiiMapping
from app.services.query_engine.base_service import (
    BaseQueryService,
    QueryExecutionOutcome,
)
from app.services.query_engine.pii_rules import QuerySpec
from app.services.query_engine.power_bi_query import build_power_bi_deeplink_query
from app.services.query_engine.power_bi_rules import POWER_BI_ACCOUNT_PII_RULES


class PowerBiDataService(BaseQueryService):
    async def deeplink_1(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int | None,
        segmentation_filters: tuple[str, ...] = (),
        user_agent_filters: tuple[str, ...] = (),
        customer_ids: tuple[str, ...] = (),
    ) -> QueryExecutionOutcome[DataRowsResponse]:
        account_tokens = self._get_tokens_by_original_values(
            original_values=customer_ids,
        )
        spec = QuerySpec(
            route_name="power_bi.deeplink_1",
            statement=build_power_bi_deeplink_query(
                event_key="topup_result",
                start_date=start_date,
                end_date=end_date,
                segmentation_filters=segmentation_filters,
                user_agent_filters=user_agent_filters,
                account_id_filters=account_tokens,
                limit=limit,
                status="processing",
            ),
            column_pii_rules=POWER_BI_ACCOUNT_PII_RULES,
        )
        return await self.execute(
            spec=spec,
            response_factory=_build_data_rows_response,
        )

    async def deeplink_2(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int | None,
        segmentation_filters: tuple[str, ...] = (),
        user_agent_filters: tuple[str, ...] = (),
        customer_ids: tuple[str, ...] = (),
    ) -> QueryExecutionOutcome[DataRowsResponse]:
        account_tokens = self._get_tokens_by_original_values(
            original_values=customer_ids,
        )
        spec = QuerySpec(
            route_name="power_bi.deeplink_2",
            statement=build_power_bi_deeplink_query(
                event_key="topup_bank_app",
                start_date=start_date,
                end_date=end_date,
                segmentation_filters=segmentation_filters,
                user_agent_filters=user_agent_filters,
                account_id_filters=account_tokens,
                limit=limit,
            ),
            column_pii_rules=POWER_BI_ACCOUNT_PII_RULES,
        )
        return await self.execute(
            spec=spec,
            response_factory=_build_data_rows_response,
        )


def _build_data_rows_response(
    rows: list[dict[str, Any]],
    missing_mappings: tuple[MissingPiiMapping, ...],
) -> DataRowsResponse:
    return DataRowsResponse(
        rows=rows,
        missing_mappings=list(missing_mappings),
    )
