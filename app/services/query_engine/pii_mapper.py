from typing import Any


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
    ) -> list[dict[str, Any]]:
        if not rows or not spec.pii_columns:
            return rows

        pii_cache = self.mapping_cache.token_to_value

        for row in rows:
            for column_name in spec.pii_columns:
                if column_name not in row:
                    continue
                rule = spec.get_pii_rule(column_name)
                if rule is None:
                    continue
                transformed_val = rule.transformer(
                    row[column_name], pii_cache, rule.pii_category
                )
                row[column_name] = transformed_val

        return rows
