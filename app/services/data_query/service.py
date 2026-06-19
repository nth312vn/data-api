from datetime import date
from typing import Any

import polars as pl

from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRepository
from app.schemas.data_query import DataRowsResponse, MissingPiiMapping
from app.services.data_query.power_bi import build_power_bi_deeplink_query
from app.services.data_query.routes import (
    DataRouteSpec,
    PiiFieldMappingRule,
    pii_token_when_length_greater_than,
)
from app.services.data_query.users import build_users_query
from app.services.pii_mapping_cache import InMemoryPiiMappingCache

DEEPLINK_ACCOUNT_ID_PII_RULE = PiiFieldMappingRule(
    pii_type="customer_id",
    token_mapper=pii_token_when_length_greater_than(
        15,
        strip_last_character=True,
    ),
)


class DataQueryService:
    def __init__(
        self,
        *,
        settings: Settings,
        trino: TrinoClient,
        pii_mappings: PiiMappingRepository,
        audit_logs: AuditLogRepository,
        mapping_cache: InMemoryPiiMappingCache,
        uow: UnitOfWork,
    ) -> None:
        self.settings = settings
        self.trino = trino
        self.pii_mappings = pii_mappings
        self.audit_logs = audit_logs
        self.mapping_cache = mapping_cache
        self.uow = uow

    async def list_users(
        self,
        *,
        actor: User,
        limit: int,
        offset: int,
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="data.users",
            statement=build_users_query(limit=limit, offset=offset),
            pii_fields=("customer_id",),
        )
        return await self._execute_route(spec=spec, actor=actor)

    async def power_bi_deeplink_1(
        self,
        *,
        actor: User,
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
            pii_fields=("accountid",),
            pii_field_rules={
                "accountid": DEEPLINK_ACCOUNT_ID_PII_RULE,
            },
        )
        response = await self._execute_route(spec=spec, actor=actor)
        response.rows = self._filter_mapped_customer_ids(
            rows=response.rows,
            customer_ids=customer_ids,
        )
        return response

    async def power_bi_deeplink_2(
        self,
        *,
        actor: User,
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
            pii_fields=("accountid",),
            pii_field_rules={
                "accountid": DEEPLINK_ACCOUNT_ID_PII_RULE,
            },
        )
        response = await self._execute_route(spec=spec, actor=actor)
        response.rows = self._filter_mapped_customer_ids(
            rows=response.rows,
            customer_ids=customer_ids,
        )
        return response

    async def _execute_route(
        self,
        *,
        spec: DataRouteSpec,
        actor: User,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        mapped_rows, missing_keys = await self._merge_pii_mappings(
            rows=rows,
            spec=spec,
        )

        missing_mappings = [
            MissingPiiMapping(
                pii_type=key.pii_type,
                token=key.token,
            )
            for key in sorted(
                missing_keys,
                key=lambda key: (key.pii_type, key.token),
            )
        ]

        if missing_mappings:
            await self._audit_missing_mappings(
                actor=actor,
                spec=spec,
                missing_mappings=missing_mappings,
            )

        return DataRowsResponse(
            rows=mapped_rows,
            missing_mappings=missing_mappings,
        )

    async def _merge_pii_mappings(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: DataRouteSpec,
    ) -> tuple[list[dict[str, Any]], set[PiiMappingKey]]:
        if not rows or not spec.pii_fields:
            return rows, set()

        frame = pl.DataFrame(rows, strict=False)
        row_id_column = self._temporary_column_name(frame, "__pii_row_id")
        frame = frame.with_row_index(row_id_column)
        keys_by_field: dict[str, list[PiiMappingKey | None]] = {}
        requested_keys: set[PiiMappingKey] = set()

        for field in spec.pii_fields:
            field_keys = [
                (
                    self._mapping_key_for_field(
                        spec=spec,
                        field=field,
                        value=row.get(field),
                    )
                    if row.get(field) is not None
                    else None
                )
                for row in rows
            ]
            keys_by_field[field] = field_keys
            requested_keys.update(key for key in field_keys if key is not None)

        mapped_values = await self._resolve_mappings(requested_keys)

        for field_index, (field, field_keys) in enumerate(keys_by_field.items()):
            if field not in frame.columns:
                continue

            token_column = self._temporary_column_name(
                frame,
                f"__pii_token_{field_index}",
            )
            mapped_column = self._temporary_column_name(
                frame,
                f"__pii_mapped_{field_index}",
            )
            frame = frame.with_columns(
                pl.Series(
                    token_column,
                    [key.token if key is not None else None for key in field_keys],
                    dtype=pl.String,
                ),
            )
            field_mappings = {
                key.token: mapped_values[key]
                for key in field_keys
                if key is not None and key in mapped_values
            }
            if field_mappings:
                mapping_frame = pl.DataFrame(
                    {
                        token_column: list(field_mappings),
                        mapped_column: list(field_mappings.values()),
                    },
                )
                frame = frame.join(
                    mapping_frame,
                    on=token_column,
                    how="left",
                    validate="m:1",
                )
                frame = frame.with_columns(
                    pl.coalesce(mapped_column, field).alias(field),
                ).drop(mapped_column)
            frame = frame.drop(token_column)

        merged_records = frame.sort(row_id_column).to_dicts()
        mapped_rows: list[dict[str, Any]] = []
        for record in merged_records:
            row_index = int(record.pop(row_id_column))
            mapped_rows.append(
                {field: record[field] for field in rows[row_index]},
            )

        return mapped_rows, requested_keys - set(mapped_values)

    async def _resolve_mappings(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, str]:
        cached = self.mapping_cache.get_many(keys)
        missing_cache_keys = keys - set(cached)
        keys_to_load = self.mapping_cache.keys_to_load(missing_cache_keys)
        if not keys_to_load:
            return cached

        db_mappings = await self.pii_mappings.get_many(keys_to_load)
        db_values = {key: mapping.mapped_value for key, mapping in db_mappings.items()}
        self.mapping_cache.set_many(db_values)
        self.mapping_cache.mark_missing(keys_to_load - set(db_values))
        return {**cached, **db_values}

    def _mapping_key_for_field(
        self,
        *,
        spec: DataRouteSpec,
        field: str,
        value: Any,
    ) -> PiiMappingKey | None:
        if value is None:
            return None
        value_string = str(value)
        rule = spec.pii_field_rules.get(field)
        if rule is None:
            return PiiMappingKey(
                pii_type=field,
                token=value_string,
            )

        token = rule.token_mapper(value)
        if token is None:
            return None

        return PiiMappingKey(
            pii_type=rule.pii_type,
            token=token,
        )

    def _filter_mapped_customer_ids(
        self,
        *,
        rows: list[dict[str, Any]],
        customer_ids: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if not rows or not customer_ids:
            return rows

        frame = pl.DataFrame(rows, strict=False).filter(
            pl.col("accountid")
            .cast(pl.String)
            .str.to_lowercase()
            .is_in([value.casefold() for value in customer_ids]),
        )
        if "stt" in frame.columns:
            frame = frame.drop("stt").with_row_index("stt", offset=1)
        return frame.to_dicts()

    @staticmethod
    def _temporary_column_name(frame: pl.DataFrame, prefix: str) -> str:
        column_name = prefix
        suffix = 1
        while column_name in frame.columns:
            column_name = f"{prefix}_{suffix}"
            suffix += 1
        return column_name

    async def _audit_missing_mappings(
        self,
        *,
        actor: User,
        spec: DataRouteSpec,
        missing_mappings: list[MissingPiiMapping],
    ) -> None:
        await self.audit_logs.create(
            AuditLog(
                user_id=actor.id,
                username=actor.username,
                api_route=spec.route_name,
                parameters={
                    "missing_mappings": [
                        mapping.model_dump() for mapping in missing_mappings
                    ],
                },
                allowed=False,
                error_message="Missing PII mapping",
            ),
        )
        await self.uow.commit()
