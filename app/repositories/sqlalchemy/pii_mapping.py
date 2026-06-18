from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Iterator
from typing import Any, cast

from sqlalchemy import and_, or_, select
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

        tokens_by_source_type: dict[tuple[str, str], set[str]] = defaultdict(set)
        for key in keys:
            tokens_by_source_type[(key.source_system, key.pii_type)].add(key.token)

        mappings: dict[PiiMappingKey, PiiMappingRecord] = {}
        for (source_system, pii_type), tokens in tokens_by_source_type.items():
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

                if model.__pii_source_attr__ is not None:
                    source_column = self._model_column(
                        model,
                        model.__pii_source_attr__,
                    )
                    source_value = model.__pii_source_value__ or source_system
                    stmt = stmt.where(source_column == source_value)

                result = await self.session.execute(stmt)
                for row in result.mappings():
                    key = PiiMappingKey(
                        source_system=source_system,
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
            source_column = (
                self._model_column(model, model.__pii_source_attr__)
                if model.__pii_source_attr__ is not None
                else None
            )
            dynamic_source = (
                source_column is not None and model.__pii_source_value__ is None
            )
            cursor: tuple[Any, Any] | None = None

            while True:
                columns = [
                    token_column.label("token"),
                    value_column.label("mapped_value"),
                ]
                if dynamic_source and source_column is not None:
                    columns.append(source_column.label("source_system"))

                stmt = select(*columns)
                if source_column is not None and model.__pii_source_value__ is not None:
                    stmt = stmt.where(source_column == model.__pii_source_value__)

                if dynamic_source and source_column is not None:
                    if cursor is not None:
                        last_source, last_token = cursor
                        stmt = stmt.where(
                            or_(
                                source_column > last_source,
                                and_(
                                    source_column == last_source,
                                    token_column > last_token,
                                ),
                            )
                        )
                    stmt = stmt.order_by(source_column, token_column)
                else:
                    if cursor is not None:
                        stmt = stmt.where(token_column > cursor[1])
                    stmt = stmt.order_by(token_column)
                stmt = stmt.limit(batch_size)

                result = await self.session.execute(stmt)
                rows = list(result.mappings())
                if not rows:
                    break

                batch: dict[PiiMappingKey, PiiMappingRecord] = {}
                for row in rows:
                    source_system = str(row["source_system"]) if dynamic_source else ""
                    key = PiiMappingKey(
                        source_system=source_system,
                        pii_type=pii_type,
                        token=str(row["token"]),
                    )
                    batch[key] = PiiMappingRecord(
                        key=key,
                        mapped_value=str(row["mapped_value"]),
                    )

                yield batch
                last_row = rows[-1]
                cursor = (
                    last_row["source_system"] if dynamic_source else "",
                    last_row["token"],
                )

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
