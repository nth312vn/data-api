import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.sql import Executable

from app.core.config import Settings
from app.utils.sql import quote_identifier_path


@dataclass(frozen=True, slots=True)
class TrinoColumn:
    name: str
    type: str
    extra: str | None
    comment: str | None


class TrinoClient(Protocol):
    async def execute(self, statement: str | Executable) -> list[dict[str, Any]]: ...

    async def get_catalogs(self) -> list[str]: ...

    async def get_schemas(self, *, catalog: str) -> list[str]: ...

    async def get_tables(self, *, catalog: str, schema: str) -> list[str]: ...

    async def get_columns(
        self,
        *,
        catalog: str,
        schema: str,
        table: str,
    ) -> list[TrinoColumn]: ...


class TrinoPythonClient:
    def __init__(
        self,
        *,
        settings: Settings,
        engine_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._engine_factory = engine_factory
        self._engine: Any | None = None
        self._engine_lock = Lock()

    async def execute(self, statement: str | Executable) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._execute_sync, statement)

    async def get_catalogs(self) -> list[str]:
        rows = await self.execute("SHOW CATALOGS")
        return self._first_column_values(rows)

    async def get_schemas(self, *, catalog: str) -> list[str]:
        catalog_name = quote_identifier_path(catalog)
        rows = await self.execute(f"SHOW SCHEMAS FROM {catalog_name}")  # noqa: S608
        return self._first_column_values(rows)

    async def get_tables(self, *, catalog: str, schema: str) -> list[str]:
        namespace = quote_identifier_path(f"{catalog}.{schema}")
        rows = await self.execute(f"SHOW TABLES FROM {namespace}")  # noqa: S608
        return self._first_column_values(rows)

    async def get_columns(
        self,
        *,
        catalog: str,
        schema: str,
        table: str,
    ) -> list[TrinoColumn]:
        table_name = quote_identifier_path(f"{catalog}.{schema}.{table}")
        rows = await self.execute(f"SHOW COLUMNS FROM {table_name}")  # noqa: S608
        return [
            TrinoColumn(
                name=str(self._row_value(row, "Column")),
                type=str(self._row_value(row, "Type")),
                extra=self._optional_row_value(row, "Extra"),
                comment=self._optional_row_value(row, "Comment"),
            )
            for row in rows
        ]

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _execute_sync(self, statement: str | Executable) -> list[dict[str, Any]]:
        engine = self._get_engine()
        try:
            with engine.connect() as connection:
                executable = (
                    text(statement) if isinstance(statement, str) else statement
                )
                result = connection.execute(executable)
                return [dict(row) for row in result.mappings().all()]
        except Exception:
            self._dispose_engine(engine)
            raise

    def _get_engine(self) -> Any:
        with self._engine_lock:
            if self._engine is None:
                self._engine = self._create_engine()
            return self._engine

    def _create_engine(self) -> Any:
        factory = self._engine_factory
        if factory is None:
            factory = create_engine
        return factory(
            self._trino_url(),
            connect_args={
                "http_scheme": self.settings.trino_http_scheme,
            },
        )

    def _trino_url(self) -> URL:
        password = None
        if self.settings.trino_password is not None:
            password_value = self.settings.trino_password.get_secret_value()
            if password_value:
                password = password_value
        return URL.create(
            "trino",
            username=self.settings.trino_user,
            password=password,
            host=self.settings.trino_host,
            port=self.settings.trino_port,
        )

    def _dispose_engine(self, engine: Any) -> None:
        with self._engine_lock:
            if self._engine is engine:
                self._engine = None
        engine.dispose()

    def _close_sync(self) -> None:
        with self._engine_lock:
            if self._engine is None:
                return
            engine = self._engine
            self._engine = None
        engine.dispose()

    def _first_column_values(self, rows: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for row in rows:
            if not row:
                continue
            values.append(str(next(iter(row.values()))))
        return values

    def _row_value(self, row: dict[str, Any], column_name: str) -> Any:
        for key, value in row.items():
            if key.lower() == column_name.lower():
                return value
        raise KeyError(column_name)

    def _optional_row_value(
        self,
        row: dict[str, Any],
        column_name: str,
    ) -> str | None:
        value = self._row_value(row, column_name)
        if value is None:
            return None
        return str(value)
