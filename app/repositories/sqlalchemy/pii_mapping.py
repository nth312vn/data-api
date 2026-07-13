from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.pii_models import PII_MAPPING_MODELS, PiiMappingModelMixin
from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord


class SQLAlchemyPiiMappingRepository:
    def __init__(
        self,
        *,
        session: AsyncSession,
        mapping_models: dict[str, type[PiiMappingModelMixin]] | None = None,
        query_batch_size: int = 500,
    ) -> None:
        if query_batch_size <= 0:
            raise ValueError("query_batch_size must be greater than zero")
        self.session = session
        self.mapping_models = mapping_models or PII_MAPPING_MODELS
        self.query_batch_size = query_batch_size

    async def get_many(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, PiiMappingRecord]:
        if not keys:
            return {}

        tokens_by_type: dict[str, set[str]] = defaultdict(set)
        for key in keys:
            tokens_by_type[key.pii_type].add(key.token)

        mappings: dict[PiiMappingKey, PiiMappingRecord] = {}
        for pii_type, tokens in tokens_by_type.items():
            model = self.mapping_models.get(pii_type)
            if model is None:
                continue

            token_column = self._model_column(model, model.__pii_token_attr__)
            value_column = self._model_column(model, model.__pii_value_attr__)
            created_at_column = self._model_column(model, model.__pii_created_at_attr__)
            for token_batch in self._batches(sorted(tokens), self.query_batch_size):
                stmt = select(
                    token_column.label("token"),
                    value_column.label("mapped_value"),
                    created_at_column.label("created_at"),
                ).where(token_column.in_(token_batch))

                result = await self.session.execute(stmt)
                for row in result.mappings():
                    key = PiiMappingKey(
                        pii_type=pii_type,
                        token=str(row["token"]),
                    )
                    mappings[key] = PiiMappingRecord(
                        pii_type=pii_type,
                        token=str(row["token"]),
                        mapped_value=str(row["mapped_value"]),
                        created_at=row["created_at"],
                    )

        return mappings

    async def get_mappings_batch(
        self,
        *,
        limit: int,
        offset: int,
        since: datetime | None = None,
    ) -> list[PiiMappingRecord]:
        """Fetch a batch of mapping records using offset pagination."""
        records: list[PiiMappingRecord] = []

        for pii_type, model in self.mapping_models.items():
            token_column = self._model_column(model, model.__pii_token_attr__)
            value_column = self._model_column(model, model.__pii_value_attr__)
            created_at_column = self._model_column(model, model.__pii_created_at_attr__)
            
            stmt = select(
                token_column.label("token"),
                value_column.label("mapped_value"),
                created_at_column.label("created_at"),
            )

            if since is not None:
                stmt = stmt.where(created_at_column > since)

            stmt = stmt.order_by(created_at_column, token_column)
            stmt = stmt.limit(limit).offset(offset)

            result = await self.session.execute(stmt)
            for row in result.mappings():
                records.append(
                    PiiMappingRecord(
                        pii_type=pii_type,
                        token=str(row["token"]),
                        mapped_value=str(row["mapped_value"]),
                        created_at=row["created_at"],
                    )
                )

        return records

    def _batches(self, values: Iterable[str], size: int) -> Iterator[tuple[str, ...]]:
        batch: list[str] = []
        for value in values:
            batch.append(value)
            if len(batch) == size:
                yield tuple(batch)
                batch = []
        if batch:
            yield tuple(batch)

    def _model_column(
        self,
        model: type[PiiMappingModelMixin],
        attribute_name: str,
    ) -> ColumnElement[Any]:
        return cast(ColumnElement[Any], getattr(model, attribute_name))
