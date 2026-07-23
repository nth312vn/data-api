import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.sql import Executable

from app.core.config import Settings
from app.core.exceptions import ExternalServiceTimeoutError
from app.utils.sql import quote_identifier_path

TRINO_MAX_ATTEMPTS = 3
TRINO_POOL_SIZE = 5
TRINO_MAX_OVERFLOW = 10
TRINO_POOL_TIMEOUT_SECONDS = 30.0
TRINO_POOL_RECYCLE_SECONDS = 1800


@dataclass(frozen=True, slots=True)
class TrinoColumn:
    name: str
    type: str
    extra: str | None
    comment: str | None


class TrinoClient(Protocol):
    async def execute(
        self,
        statement: str | Executable,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

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

    async def execute(
        self,
        statement: str | Executable,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._execute_sync, statement, parameters),
                timeout=self.settings.trino_query_timeout_seconds,
            )
        except TimeoutError as exc:
            self._dispose_current_engine()
            raise ExternalServiceTimeoutError("Trino query") from exc

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

    def _execute_sync(
        self,
        statement: str | Executable,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        engine = self._get_engine()
        try:
            with engine.connect() as connection:
                executable = (
                    text(statement) if isinstance(statement, str) else statement
                )
                if parameters:
                    bind_rules = []
                    for k, v in parameters.items():
                        if isinstance(v, (list, tuple)):
                            bind_rules.append(bindparam(k, expanding=True))
                    if bind_rules:
                        executable = executable.bindparams(*bind_rules)
                    result = connection.execute(executable, parameters)
                else:
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
            pool_size=TRINO_POOL_SIZE,
            max_overflow=TRINO_MAX_OVERFLOW,
            pool_timeout=TRINO_POOL_TIMEOUT_SECONDS,
            pool_recycle=TRINO_POOL_RECYCLE_SECONDS,
            pool_use_lifo=True,
            connect_args={
                "http_scheme": self.settings.trino_http_scheme,
                "request_timeout": self.settings.trino_request_timeout_seconds,
                "max_attempts": TRINO_MAX_ATTEMPTS,
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

    def _dispose_current_engine(self) -> None:
        with self._engine_lock:
            engine = self._engine
            self._engine = None
        if engine is not None:
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
