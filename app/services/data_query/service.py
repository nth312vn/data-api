from dataclasses import dataclass
from datetime import date
from typing import Any

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


@dataclass(frozen=True, slots=True)
class _PiiFieldReference:
    row_index: int
    field: str


@dataclass(frozen=True, slots=True)
class _PiiMappingPlan:
    rows: list[dict[str, Any]]
    requested_keys: set[PiiMappingKey]
    references_by_key: dict[PiiMappingKey, list[_PiiFieldReference]]


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
            source_system="trino",
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
        limit: int,
        customer_ids: tuple[str, ...] = (),
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="power_bi.deeplink_1",
            source_system="trino",
            statement=build_power_bi_deeplink_query(
                event_key="topup_result",
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                customer_ids=customer_ids,
                status="processing",
            ),
            pii_fields=("accountid",),
            pii_field_rules={
                "accountid": DEEPLINK_ACCOUNT_ID_PII_RULE,
            },
        )
        return await self._execute_route(spec=spec, actor=actor)

    async def power_bi_deeplink_2(
        self,
        *,
        actor: User,
        start_date: date,
        end_date: date,
        limit: int,
        customer_ids: tuple[str, ...] = (),
    ) -> DataRowsResponse:
        spec = DataRouteSpec(
            route_name="power_bi.deeplink_2",
            source_system="trino",
            statement=build_power_bi_deeplink_query(
                event_key="topup_bank_app",
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                customer_ids=customer_ids,
            ),
            pii_fields=("accountid",),
            pii_field_rules={
                "accountid": DEEPLINK_ACCOUNT_ID_PII_RULE,
            },
        )
        return await self._execute_route(spec=spec, actor=actor)

    async def _execute_route(
        self,
        *,
        spec: DataRouteSpec,
        actor: User,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        mapping_plan = self._prepare_mapping_plan(rows=rows, spec=spec)
        mapped_values = await self._resolve_mappings(mapping_plan.requested_keys)
        missing_keys = mapping_plan.requested_keys - set(mapped_values)

        self._apply_resolved_mappings(
            mapping_plan=mapping_plan,
            mapped_values=mapped_values,
        )

        missing_mappings = [
            MissingPiiMapping(
                source_system=key.source_system,
                pii_type=key.pii_type,
                token=key.token,
            )
            for key in sorted(
                missing_keys,
                key=lambda key: (key.source_system, key.pii_type, key.token),
            )
        ]

        if missing_mappings:
            await self._audit_missing_mappings(
                actor=actor,
                spec=spec,
                missing_mappings=missing_mappings,
            )

        return DataRowsResponse(
            rows=mapping_plan.rows,
            missing_mappings=missing_mappings,
        )

    def _prepare_mapping_plan(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: DataRouteSpec,
    ) -> _PiiMappingPlan:
        references_by_key: dict[PiiMappingKey, list[_PiiFieldReference]] = {}
        if len(spec.pii_fields) == 1:
            field = spec.pii_fields[0]
            for row_index, row in enumerate(rows):
                self._add_mapping_reference(
                    references_by_key=references_by_key,
                    spec=spec,
                    row_index=row_index,
                    field=field,
                    value=row.get(field),
                )
            return _PiiMappingPlan(
                rows=rows,
                requested_keys=set(references_by_key),
                references_by_key=references_by_key,
            )

        for row_index, row in enumerate(rows):
            for field in spec.pii_fields:
                self._add_mapping_reference(
                    references_by_key=references_by_key,
                    spec=spec,
                    row_index=row_index,
                    field=field,
                    value=row.get(field),
                )
        return _PiiMappingPlan(
            rows=rows,
            requested_keys=set(references_by_key),
            references_by_key=references_by_key,
        )

    def _add_mapping_reference(
        self,
        *,
        references_by_key: dict[PiiMappingKey, list[_PiiFieldReference]],
        spec: DataRouteSpec,
        row_index: int,
        field: str,
        value: Any,
    ) -> None:
        if value is None:
            return
        key = self._mapping_key_for_field(
            spec=spec,
            field=field,
            value=value,
        )
        if key is None:
            return
        references_by_key.setdefault(key, []).append(
            _PiiFieldReference(
                row_index=row_index,
                field=field,
            ),
        )

    async def _resolve_mappings(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, str]:
        cached = self.mapping_cache.get_many(keys)
        missing_cache_keys = keys - set(cached)
        db_mappings = await self.pii_mappings.get_many(missing_cache_keys)
        db_values = {key: mapping.mapped_value for key, mapping in db_mappings.items()}
        self.mapping_cache.set_many(db_values)
        return {**cached, **db_values}

    def _apply_resolved_mappings(
        self,
        *,
        mapping_plan: _PiiMappingPlan,
        mapped_values: dict[PiiMappingKey, str],
    ) -> None:
        for key, mapped_value in mapped_values.items():
            references = mapping_plan.references_by_key.get(key, ())
            for reference in references:
                mapping_plan.rows[reference.row_index][reference.field] = (
                    mapped_value
                )

    def _mapping_key_for_field(
        self,
        *,
        spec: DataRouteSpec,
        field: str,
        value: Any,
    ) -> PiiMappingKey | None:
        value_string = str(value)
        rule = spec.pii_field_rules.get(field)
        if rule is None:
            return PiiMappingKey(
                source_system=spec.source_system,
                pii_type=field,
                token=value_string,
            )

        token = rule.token_mapper(value)
        if token is None:
            return None

        return PiiMappingKey(
            source_system=spec.source_system,
            pii_type=rule.pii_type,
            token=token,
        )

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
                    "source_system": spec.source_system,
                    "missing_mappings": [
                        mapping.model_dump() for mapping in missing_mappings
                    ],
                },
                allowed=False,
                error_message="Missing PII mapping",
            ),
        )
        await self.uow.commit()
