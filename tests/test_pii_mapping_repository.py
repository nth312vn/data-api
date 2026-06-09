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
