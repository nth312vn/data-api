import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from threading import Lock
from typing import Any, Protocol, cast

from app.core.config import Settings
from app.utils.sql import quote_identifier_path


@dataclass(frozen=True, slots=True)
class TrinoColumn:
    name: str
    type: str
    extra: str | None
    comment: str | None


class TrinoClient(Protocol):
    async def execute(self, sql: str) -> list[dict[str, Any]]: ...

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


class DbApiTrinoClient:
    def __init__(
        self,
        *,
        settings: Settings,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._connect_factory = connect_factory
        self._connection: Any | None = None
        self._connection_lock = Lock()

    async def execute(self, sql: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._execute_sync, sql)

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

    def _execute_sync(self, sql: str) -> list[dict[str, Any]]:
        with self._connection_lock:
            connection = self._get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(sql)
                columns = self._column_names(cursor.description)
                rows = cursor.fetchall()
                return [dict(zip(columns, row, strict=True)) for row in rows]
            except Exception:
                self._close_connection(connection)
                self._connection = None
                raise
            finally:
                close_cursor = getattr(cursor, "close", None)
                if close_cursor is not None:
                    close_cursor()

    def _get_connection(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(
                host=self.settings.trino_host,
                port=self.settings.trino_port,
                user=self.settings.trino_user,
                http_scheme=self.settings.trino_http_scheme,
            )
        return self._connection

    def _connect(self, **kwargs: Any) -> Any:
        connect = self._connect_factory
        if connect is None:
            connect = cast(Callable[..., Any], import_module("trino.dbapi").connect)
        return connect(**kwargs)

    def _close_sync(self) -> None:
        with self._connection_lock:
            if self._connection is None:
                return
            connection = self._connection
            self._connection = None
            self._close_connection(connection)

    def _close_connection(self, connection: Any) -> None:
        connection.close()

    def _column_names(self, description: Sequence[Sequence[Any]] | None) -> list[str]:
        if description is None:
            return []
        return [str(column[0]) for column in description]

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
