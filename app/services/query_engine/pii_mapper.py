from typing import Any

from app.repositories.interfaces.pii_mapping import PiiMappingKey
from app.services.query_engine.pii_rules import QuerySpec
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


class PiiMapper:
    """Map PII token fields in query result rows using the in-memory cache.

    Pure cache-based. For each row, each rule's transformer receives the full
    cache snapshot and decides how to transform the field value.
    """

    def __init__(
        self,
        *,
        mapping_cache: InMemoryPiiMappingCache,
    ) -> None:
        self.mapping_cache = mapping_cache

    async def map_pii_fields(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: QuerySpec,
    ) -> tuple[list[dict[str, Any]], set[PiiMappingKey]]:
        if not rows or not spec.pii_columns:
            return rows, set()

        # Get toàn bộ cache 1 lần — tất cả rule transformers dùng chung snapshot này
        pii_cache = self.mapping_cache.get_all()

        for row in rows:
            for column_name in spec.pii_columns:
                if column_name not in row:
                    continue
                rule = spec.get_pii_rule(column_name)
                if rule is None:
                    continue
                row[column_name] = rule.transformer(
                    row[column_name], pii_cache, rule.pii_category
                )

        return rows, set()
