from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Iterator
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
            for token_batch in self._batches(sorted(tokens), self.query_batch_size):
                stmt = select(
                    token_column.label("token"),
                    value_column.label("mapped_value"),
                ).where(token_column.in_(token_batch))

                result = await self.session.execute(stmt)
                for row in result.mappings():
                    key = PiiMappingKey(
                        pii_type=pii_type,
                        token=str(row["token"]),
                    )
                    mappings[key] = PiiMappingRecord(
                        key=key,
                        mapped_value=str(row["mapped_value"]),
                    )

        return mappings

    async def iter_snapshot_batches(
        self,
        *,
        batch_size: int,
    ) -> AsyncIterator[dict[PiiMappingKey, PiiMappingRecord]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        for pii_type, model in self.mapping_models.items():
            token_column = self._model_column(model, model.__pii_token_attr__)
            value_column = self._model_column(model, model.__pii_value_attr__)
            cursor: Any | None = None

            while True:
                stmt = select(
                    token_column.label("token"),
                    value_column.label("mapped_value"),
                )
                if cursor is not None:
                    stmt = stmt.where(token_column > cursor)
                stmt = stmt.order_by(token_column)
                stmt = stmt.limit(batch_size)

                result = await self.session.execute(stmt)
                rows = list(result.mappings())
                if not rows:
                    break

                batch: dict[PiiMappingKey, PiiMappingRecord] = {}
                for row in rows:
                    key = PiiMappingKey(
                        pii_type=pii_type,
                        token=str(row["token"]),
                    )
                    batch[key] = PiiMappingRecord(
                        key=key,
                        mapped_value=str(row["mapped_value"]),
                    )

                yield batch
                cursor = rows[-1]["token"]

                if len(rows) < batch_size:
                    break

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
