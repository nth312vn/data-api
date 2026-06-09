from datetime import date
from hashlib import sha256
from typing import Any

from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.models.audit_log import AuditLog, AuditLogStatus
from app.models.user import User
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRepository
from app.schemas.data_query import DataRowsResponse, MissingPiiMapping
from app.services.data_query.power_bi import build_power_bi_deeplink_query
from app.services.data_query.routes import DataRouteSpec
from app.services.data_query.users import build_users_query
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


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
            pii_fields=(),
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
            pii_fields=(),
        )
        return await self._execute_route(spec=spec, actor=actor)

    async def _execute_route(
        self,
        *,
        spec: DataRouteSpec,
        actor: User,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.statement)
        requested_keys = self._collect_mapping_keys(rows, spec)
        mapped_values = await self._resolve_mappings(requested_keys)
        missing_keys = requested_keys - set(mapped_values)

        mapped_rows = self._apply_mappings(
            rows=rows,
            spec=spec,
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

        return DataRowsResponse(rows=mapped_rows, missing_mappings=missing_mappings)

    def _collect_mapping_keys(
        self,
        rows: list[dict[str, Any]],
        spec: DataRouteSpec,
    ) -> set[PiiMappingKey]:
        keys: set[PiiMappingKey] = set()
        for row in rows:
            for field in spec.pii_fields:
                value = row.get(field)
                if value is None:
                    continue
                keys.add(
                    PiiMappingKey(
                        source_system=spec.source_system,
                        pii_type=field,
                        token=str(value),
                    ),
                )
        return keys

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

    def _apply_mappings(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: DataRouteSpec,
        mapped_values: dict[PiiMappingKey, str],
    ) -> list[dict[str, Any]]:
        mapped_rows: list[dict[str, Any]] = []
        for row in rows:
            mapped_row = row.copy()
            for field in spec.pii_fields:
                value = row.get(field)
                if value is None:
                    continue
                key = PiiMappingKey(
                    source_system=spec.source_system,
                    pii_type=field,
                    token=str(value),
                )
                if key in mapped_values:
                    mapped_row[field] = mapped_values[key]
            mapped_rows.append(mapped_row)
        return mapped_rows

    async def _audit_missing_mappings(
        self,
        *,
        actor: User,
        spec: DataRouteSpec,
        missing_mappings: list[MissingPiiMapping],
    ) -> None:
        await self.audit_logs.create(
            AuditLog(
                event_type="pii_mapping_missing",
                actor_user_id=actor.id,
                status=AuditLogStatus.missing_mapping,
                payload={
                    "route": spec.route_name,
                    "source_system": spec.source_system,
                    "sql_sha256": sha256(str(spec.statement).encode()).hexdigest(),
                    "missing_mappings": [
                        mapping.model_dump() for mapping in missing_mappings
                    ],
                },
            ),
        )
        await self.uow.commit()
