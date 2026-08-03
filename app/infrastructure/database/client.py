from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable


class PostgresClient(Protocol):
    async def execute(
        self,
        statement: str | Executable,
        parameters: Mapping[str, object] | None = None,
    ) -> list[dict[str, Any]]: ...


class SQLAlchemyPostgresClient:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def execute(
        self,
        statement: str | Executable,
        parameters: Mapping[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        executable = text(statement) if isinstance(statement, str) else statement
        result = await self.session.execute(executable, parameters or {})
        return [dict(row) for row in result.mappings().all()]
