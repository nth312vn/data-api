from typing import Any

from app.schemas.common import MissingPiiMapping
from app.services.account_map_in_memory import AccountMapInMemory
from app.services.query_engine.pii_rules import QuerySpec


class PiiMapper:
    """Map PII token fields in query result rows using the in-memory cache.

    Pure cache-based. For each row, each rule's transformer receives the full
    cache snapshot and decides how to transform the field value.
    """

    def __init__(
        self,
        *,
        mapping_cache: AccountMapInMemory,
    ) -> None:
        self.mapping_cache = mapping_cache

    async def map_pii_fields(
        self,
        *,
        rows: list[dict[str, Any]],
        spec: QuerySpec,
    ) -> tuple[list[dict[str, Any]], list[MissingPiiMapping]]:
        if not spec.pii_columns:
            raise ValueError(f"Query {spec.route_name} has no PII mapping rules")

        if not rows:
            return rows, []

        token_to_value = self.mapping_cache.token_to_value
        missing_mappings: list[MissingPiiMapping] = []

        for row in rows:
            for column_name, rule in spec.column_pii_rules.items():
                if column_name not in row:
                    continue
                value = row[column_name]
                if value is None:
                    continue
                transformed_val = rule.transformer(
                    value,
                    token_to_value,
                )
                if transformed_val is None:
                    missing_mappings.append(
                        MissingPiiMapping(
                            column_name=column_name,
                            value=value,
                        )
                    )
                row[column_name] = (
                    transformed_val if transformed_val is not None else None
                )

        return rows, missing_mappings
