from typing import Any

from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRepository
from app.services.data_query.routes import DataRouteSpec
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


class PiiMapper:
    def __init__(
        self,
        *,
        pii_mappings: PiiMappingRepository,
        mapping_cache: InMemoryPiiMappingCache,
    ) -> None:
        self.pii_mappings = pii_mappings
        self.mapping_cache = mapping_cache

    async def map_pii_fields(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: DataRouteSpec,
    ) -> tuple[list[dict[str, Any]], set[PiiMappingKey]]:
        if not rows or not spec.effective_pii_fields:
            return rows, set()

        keys_by_field: dict[str, list[tuple[PiiMappingKey, str] | None]] = {}
        requested_keys: set[PiiMappingKey] = set()

        for field in spec.effective_pii_fields:
            field_keys = []
            for row in rows:
                key_tuple = self._build_mapping_key(
                    spec=spec,
                    field=field,
                    value=row.get(field),
                )
                field_keys.append(key_tuple)
                if key_tuple is not None:
                    requested_keys.add(key_tuple[0])
            keys_by_field[field] = field_keys

        mapped_values = await self._resolve_mappings(requested_keys)

        for row_idx, row in enumerate(rows):
            for field in spec.effective_pii_fields:
                if field not in row:
                    continue

                key_tuple = keys_by_field[field][row_idx]
                if key_tuple is None:
                    continue

                key, suffix = key_tuple
                mapped_value = mapped_values.get(key)
                if mapped_value is not None:
                    row[field] = mapped_value + suffix

        missing_keys = requested_keys - set(mapped_values)
        return rows, missing_keys

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

    def _build_mapping_key(
        self,
        *,
        spec: DataRouteSpec,
        field: str,
        value: Any,
    ) -> tuple[PiiMappingKey, str] | None:
        if value is None:
            return None

        rule = spec.get_pii_rule(field)
        if rule is not None:
            result = rule.token_mapper(value)
            if result is None:
                return None
            token, suffix = result
            return PiiMappingKey(pii_type=rule.pii_type, token=token), suffix

        from app.services.data_query.routes import default_pii_token_mapper
        result = default_pii_token_mapper(value)
        if result is None:
            return None
        token, suffix = result
        return PiiMappingKey(pii_type=field, token=token), suffix
