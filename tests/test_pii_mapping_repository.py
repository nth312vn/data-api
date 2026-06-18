from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.pii_models import PII_MAPPING_MODELS, CustomerIdentityPiiMapping
from app.repositories.interfaces.pii_mapping import PiiMappingKey
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository


class FakeResult:
    def mappings(self) -> list[dict[str, str]]:
        return [
            {
                "token": "customer-1",
                "mapped_value": "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
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
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, str]]:
        return self.rows


class SnapshotSession:
    def __init__(self, result_rows: list[list[dict[str, str]]]) -> None:
        self.result_rows = result_rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> RowsResult:
        self.statements.append(stmt)
        return RowsResult(self.result_rows.pop(0))


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
        source_system="trino",
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
    keys = {
        PiiMappingKey("trino", "customer_id", f"customer-{index}") for index in range(5)
    }

    await repository.get_many(keys)

    assert len(session.statements) == 3
    assert [
        len(statement.compile().params["customer_id_1"])
        for statement in session.statements
    ] == [2, 2, 1]


@pytest.mark.asyncio
async def test_snapshot_uses_bounded_keyset_queries() -> None:
    session = SnapshotSession(
        [
            [
                {"token": "customer-1", "mapped_value": "uuid-1"},
                {"token": "customer-2", "mapped_value": "uuid-2"},
            ],
            [{"token": "customer-3", "mapped_value": "uuid-3"}],
        ]
    )
    repository = SQLAlchemyPiiMappingRepository(
        session=cast(AsyncSession, session),
        mapping_models={"customer_id": CustomerIdentityPiiMapping},
    )

    batches = [
        batch
        async for batch in repository.iter_snapshot_batches(
            batch_size=2,
        )
    ]

    assert [len(batch) for batch in batches] == [2, 1]
    assert len(session.statements) == 2
    assert all(" LIMIT " in str(statement) for statement in session.statements)
    assert " ORDER BY customer_identity_map.customer_id" in str(session.statements[0])
    assert "customer_identity_map.customer_id >" in str(session.statements[1])
