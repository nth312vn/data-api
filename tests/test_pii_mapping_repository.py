from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.pii_models import PII_MAPPING_MODELS, CustomerIdentityPiiMapping
from app.repositories.interfaces.pii_mapping import PiiMappingKey
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository


from datetime import datetime

class FakeResult:
    def mappings(self) -> list[dict[str, Any]]:
        return [
            {
                "token": "customer-1",
                "mapped_value": "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
                "created_at": datetime.now(),
            }
        ]


class FakeSession:
    def __init__(self) -> None:
        self.sql: str | None = None

    async def execute(self, stmt: Any) -> FakeResult:
        self.sql = str(stmt)
        return FakeResult()


class EmptyResult:
    def mappings(self) -> list[dict[str, str]]:
        return []


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> EmptyResult:
        self.statements.append(stmt)
        return EmptyResult()


class RowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows


class SnapshotSession:
    def __init__(self, result_rows: list[dict[str, Any]]) -> None:
        self.result_rows = result_rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> RowsResult:
        self.statements.append(stmt)
        return RowsResult(self.result_rows)


def test_pii_mapping_models_are_registered_by_pii_type() -> None:
    assert PII_MAPPING_MODELS["customer_id"] is CustomerIdentityPiiMapping


def test_customer_identity_mapping_uses_customer_id_text_and_uuid_value() -> None:
    customer_id_column = CustomerIdentityPiiMapping.__table__.c.customer_id
    uuid_column = CustomerIdentityPiiMapping.__table__.c.uuid

    assert CustomerIdentityPiiMapping.__pii_token_attr__ == "customer_id"
    assert CustomerIdentityPiiMapping.__pii_value_attr__ == "uuid"
    assert str(customer_id_column.type) == "TEXT"
    assert str(uuid_column.type) == "CHAR(36)"


@pytest.mark.asyncio
async def test_pii_mapping_repository_uses_model_specific_table_and_columns() -> None:
    session = FakeSession()
    repository = SQLAlchemyPiiMappingRepository(
        session=cast(AsyncSession, session),
        mapping_models={"customer_id": CustomerIdentityPiiMapping},
    )

    key = PiiMappingKey(
        pii_type="customer_id",
        token="customer-1",
    )
    mappings = await repository.get_many({key})

    assert mappings[key].mapped_value == "7c37bb4b-0e15-4fb9-b589-f57211ac1679"
    assert session.sql is not None
    assert "FROM customer_identity_map" in session.sql
    assert "customer_identity_map.customer_id AS token" in session.sql
    assert "customer_identity_map.uuid AS mapped_value" in session.sql


@pytest.mark.asyncio
async def test_pii_mapping_repository_splits_misses_into_bounded_batches() -> None:
    session = RecordingSession()
    repository = SQLAlchemyPiiMappingRepository(
        session=cast(AsyncSession, session),
        mapping_models={"customer_id": CustomerIdentityPiiMapping},
        query_batch_size=2,
    )
    keys = {PiiMappingKey("customer_id", f"customer-{index}") for index in range(5)}

    await repository.get_many(keys)

    assert len(session.statements) == 3
    assert [
        len(statement.compile().params["customer_id_1"])
        for statement in session.statements
    ] == [2, 2, 1]


@pytest.mark.asyncio
async def test_fetch_all_mappings_orders_by_created_at() -> None:
    now = datetime.now()
    session = SnapshotSession(
        [
            {"token": "customer-1", "mapped_value": "uuid-1", "created_at": now},
            {"token": "customer-2", "mapped_value": "uuid-2", "created_at": now},
            {"token": "customer-3", "mapped_value": "uuid-3", "created_at": now},
        ]
    )
    repository = SQLAlchemyPiiMappingRepository(
        session=cast(AsyncSession, session),
        mapping_models={"customer_id": CustomerIdentityPiiMapping},
    )

    records = await repository.fetch_all_mappings()

    assert len(records) == 3
    assert len(session.statements) == 1
    assert " ORDER BY customer_identity_map.created_at" in str(session.statements[0])
