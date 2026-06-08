from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.pii_models import PII_MAPPING_MODELS, EmailPiiMapping
from app.repositories.interfaces.pii_mapping import PiiMappingKey
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository


class FakeResult:
    def mappings(self) -> list[dict[str, str]]:
        return [{"token": "email-token-1", "mapped_value": "user@example.com"}]


class FakeSession:
    def __init__(self) -> None:
        self.sql: str | None = None

    async def execute(self, stmt: Any) -> FakeResult:
        self.sql = str(stmt)
        return FakeResult()


def test_pii_mapping_models_are_registered_by_pii_type() -> None:
    assert PII_MAPPING_MODELS["email_token"] is EmailPiiMapping


@pytest.mark.asyncio
async def test_pii_mapping_repository_uses_model_specific_table_and_columns() -> None:
    session = FakeSession()
    repository = SQLAlchemyPiiMappingRepository(
        session=cast(AsyncSession, session),
        mapping_models={"email_token": EmailPiiMapping},
    )

    key = PiiMappingKey(
        source_system="trino",
        pii_type="email_token",
        token="email-token-1",
    )
    mappings = await repository.get_many({key})

    assert mappings[key].mapped_value == "user@example.com"
    assert session.sql is not None
    assert "FROM pii_email_lookup" in session.sql
    assert "pii_email_lookup.email_hash AS token" in session.sql
    assert "pii_email_lookup.email_address AS mapped_value" in session.sql
    assert "pii_email_lookup.system_code = :system_code_1" in session.sql
