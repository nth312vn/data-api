from collections import defaultdict
from typing import cast

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
    ) -> None:
        self.session = session
        self.mapping_models = mapping_models or PII_MAPPING_MODELS

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
            stmt = select(
                token_column.label("token"),
                value_column.label("mapped_value"),
            ).where(token_column.in_(tokens))

            if model.__pii_source_attr__ is not None:
                source_column = self._model_column(model, model.__pii_source_attr__)
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

    def _model_column(
        self,
        model: type[PiiMappingModelMixin],
        attribute_name: str,
    ) -> ColumnElement[str]:
        return cast(ColumnElement[str], getattr(model, attribute_name))
