from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.models.audit_log import AuditLog, AuditLogStatus
from app.models.user import User
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRepository
from app.schemas.data_query import (
    DataRowsResponse,
    MissingPiiMapping,
)
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.utils.sql import quote_identifier_path


@dataclass(frozen=True, slots=True)
class DataRouteSpec:
    route_name: str
    source_system: str
    sql: str
    pii_fields: tuple[str, ...]


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
            sql=self._build_users_query(limit=limit, offset=offset),
            pii_fields=("email_token", "phone_token"),
        )
        return await self._execute_route(spec=spec, actor=actor)

    async def _execute_route(
        self,
        *,
        spec: DataRouteSpec,
        actor: User,
    ) -> DataRowsResponse:
        rows = await self.trino.execute(spec.sql)
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

    def _build_users_query(self, *, limit: int, offset: int) -> str:
        table_name = quote_identifier_path(
            ".".join(
                [
                    self.settings.trino_catalog,
                    self.settings.trino_schema,
                    self.settings.trino_users_table,
                ],
            ),
        )
        sql = f"""
            SELECT
                user_id,
                email_token,
                phone_token,
                full_name,
                created_at
            FROM {table_name}
            ORDER BY created_at DESC
            OFFSET {offset}
            LIMIT {limit}
        """  # noqa: S608
        return sql

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
        db_values = {
            key: mapping.mapped_value for key, mapping in db_mappings.items()
        }
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
                    "sql_sha256": sha256(spec.sql.encode()).hexdigest(),
                    "missing_mappings": [
                        mapping.model_dump() for mapping in missing_mappings
                    ],
                },
            ),
        )
        await self.uow.commit()
