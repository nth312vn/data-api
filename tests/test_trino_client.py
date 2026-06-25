import time
from typing import Any

import pytest

from app.core.config import Settings
from app.core.exceptions import ExternalServiceTimeoutError
from app.infrastructure.trino.client import TrinoColumn, TrinoPythonClient


class FakeMappingResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeResult:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        self.columns = columns
        self.rows = rows

    def mappings(self) -> FakeMappingResult:
        return FakeMappingResult(
            [dict(zip(self.columns, row, strict=True)) for row in self.rows],
        )


class FakeConnection:
    def __init__(
        self,
        *,
        responses: dict[str, tuple[list[str], list[tuple[Any, ...]]]],
        executed_sql: list[str],
    ) -> None:
        self._responses = responses
        self._executed_sql = executed_sql
        self.closed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def execute(self, statement: Any) -> FakeResult:
        sql = str(statement)
        self._executed_sql.append(sql)
        columns, rows = self._responses[sql]
        return FakeResult(columns, rows)


class FakeEngine:
    def __init__(
        self,
        responses: dict[str, tuple[list[str], list[tuple[Any, ...]]]],
    ) -> None:
        self.responses = responses
        self.executed_sql: list[str] = []
        self.connections: list[FakeConnection] = []
        self.disposed = False

    def connect(self) -> FakeConnection:
        connection = FakeConnection(
            responses=self.responses,
            executed_sql=self.executed_sql,
        )
        self.connections.append(connection)
        return connection

    def dispose(self) -> None:
        self.disposed = True


def make_settings() -> Settings:
    return Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars")


@pytest.mark.asyncio
async def test_trino_client_uses_sqlalchemy_url_and_password() -> None:
    captured: dict[str, Any] = {}
    engine = FakeEngine({"SELECT 1": (["value"], [(1,)])})

    def engine_factory(*args: Any, **kwargs: Any) -> FakeEngine:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return engine

    client = TrinoPythonClient(
        settings=Settings(
            jwt_secret_key="test-secret-key-with-at-least-32-chars",
            trino_password="secret-password",
        ),
        engine_factory=engine_factory,
    )

    result = await client.execute("SELECT 1")

    url = captured["args"][0]
    assert result == [{"value": 1}]
    assert url.drivername == "trino"
    assert url.username == "data-api"
    assert url.password == "secret-password"
    assert url.host == "localhost"
    assert url.port == 8080
    assert captured["kwargs"] == {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30.0,
        "pool_recycle": 1800,
        "pool_use_lifo": True,
        "connect_args": {
            "http_scheme": "http",
            "request_timeout": 30.0,
            "max_attempts": 3,
        },
    }


@pytest.mark.asyncio
async def test_trino_client_reuses_engine_between_queries() -> None:
    engines: list[FakeEngine] = []

    def engine_factory(*_args: Any, **_kwargs: Any) -> FakeEngine:
        engine = FakeEngine(
            {
                "SELECT 1": (["value"], [(1,)]),
                "SELECT 2": (["value"], [(2,)]),
            },
        )
        engines.append(engine)
        return engine

    client = TrinoPythonClient(
        settings=make_settings(),
        engine_factory=engine_factory,
    )

    first_result = await client.execute("SELECT 1")
    second_result = await client.execute("SELECT 2")

    assert first_result == [{"value": 1}]
    assert second_result == [{"value": 2}]
    assert len(engines) == 1
    assert engines[0].disposed is False
    assert engines[0].executed_sql == ["SELECT 1", "SELECT 2"]
    assert all(connection.closed for connection in engines[0].connections)

    await client.close()

    assert engines[0].disposed is True


@pytest.mark.asyncio
async def test_trino_client_recreates_engine_after_query_failure() -> None:
    class FailingConnection(FakeConnection):
        def execute(self, statement: Any) -> FakeResult:
            raise RuntimeError("query failed")

    class FailingEngine(FakeEngine):
        def connect(self) -> FakeConnection:
            connection = FailingConnection(
                responses=self.responses,
                executed_sql=self.executed_sql,
            )
            self.connections.append(connection)
            return connection

    engines: list[FakeEngine] = []
    engine_calls = 0

    def engine_factory(*_args: Any, **_kwargs: Any) -> FakeEngine:
        nonlocal engine_calls
        engine_calls += 1
        if engine_calls == 1:
            engine: FakeEngine = FailingEngine({})
        else:
            engine = FakeEngine({"SELECT 1": (["value"], [(1,)])})
        engines.append(engine)
        return engine

    client = TrinoPythonClient(
        settings=make_settings(),
        engine_factory=engine_factory,
    )

    with pytest.raises(RuntimeError, match="query failed"):
        await client.execute("SELECT broken")

    assert engines[0].disposed is True

    result = await client.execute("SELECT 1")

    assert result == [{"value": 1}]
    assert len(engines) == 2


@pytest.mark.asyncio
async def test_trino_client_disposes_engine_after_query_timeout() -> None:
    class SlowConnection(FakeConnection):
        def execute(self, statement: Any) -> FakeResult:
            time.sleep(0.05)
            return super().execute(statement)

    class SlowEngine(FakeEngine):
        def connect(self) -> FakeConnection:
            connection = SlowConnection(
                responses=self.responses,
                executed_sql=self.executed_sql,
            )
            self.connections.append(connection)
            return connection

    engine = SlowEngine({"SELECT slow": (["value"], [(1,)])})

    def engine_factory(*_args: Any, **_kwargs: Any) -> FakeEngine:
        return engine

    client = TrinoPythonClient(
        settings=Settings(
            jwt_secret_key="test-secret-key-with-at-least-32-chars",
            trino_query_timeout_seconds=0.01,
        ),
        engine_factory=engine_factory,
    )

    with pytest.raises(ExternalServiceTimeoutError):
        await client.execute("SELECT slow")

    assert engine.disposed is True


@pytest.mark.asyncio
async def test_trino_client_reads_catalog_schema_table_and_column_metadata() -> None:
    engine = FakeEngine(
        {
            "SHOW CATALOGS": (
                ["Catalog"],
                [("hive",), ("iceberg",)],
            ),
            'SHOW SCHEMAS FROM "hive"': (
                ["Schema"],
                [("default",), ("analytics",)],
            ),
            'SHOW TABLES FROM "hive"."default"': (
                ["Table"],
                [("users",), ("orders",)],
            ),
            'SHOW COLUMNS FROM "hive"."default"."users"': (
                ["Column", "Type", "Extra", "Comment"],
                [
                    ("user_id", "varchar", "", "primary user id"),
                    ("created_at", "timestamp(3)", "", None),
                ],
            ),
        },
    )

    def engine_factory(*_args: Any, **_kwargs: Any) -> FakeEngine:
        return engine

    client = TrinoPythonClient(
        settings=make_settings(),
        engine_factory=engine_factory,
    )

    catalogs = await client.get_catalogs()
    schemas = await client.get_schemas(catalog="hive")
    tables = await client.get_tables(catalog="hive", schema="default")
    columns = await client.get_columns(
        catalog="hive",
        schema="default",
        table="users",
    )

    assert catalogs == ["hive", "iceberg"]
    assert schemas == ["default", "analytics"]
    assert tables == ["users", "orders"]
    assert columns == [
        TrinoColumn(
            name="user_id",
            type="varchar",
            extra="",
            comment="primary user id",
        ),
        TrinoColumn(
            name="created_at",
            type="timestamp(3)",
            extra="",
            comment=None,
        ),
    ]
    assert engine.executed_sql == [
        "SHOW CATALOGS",
        'SHOW SCHEMAS FROM "hive"',
        'SHOW TABLES FROM "hive"."default"',
        'SHOW COLUMNS FROM "hive"."default"."users"',
    ]
