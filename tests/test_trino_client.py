from typing import Any

import pytest

from app.core.config import Settings
from app.infrastructure.trino.client import DbApiTrinoClient, TrinoColumn


class FakeCursor:
    description = [("value",)]

    def __init__(self, rows: list[tuple[int]]) -> None:
        self.rows = rows
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)

    def fetchall(self) -> list[tuple[int]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor(rows=[(len(self.cursors) + 1,)])
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        self.closed = True


class MetadataCursor:
    def __init__(
        self,
        *,
        responses: dict[str, tuple[list[str], list[tuple[Any, ...]]]],
        executed_sql: list[str],
    ) -> None:
        self._responses = responses
        self._executed_sql = executed_sql
        self.description: list[tuple[str]] | None = None
        self.rows: list[tuple[Any, ...]] = []
        self.closed = False

    def execute(self, sql: str) -> None:
        self._executed_sql.append(sql)
        columns, rows = self._responses[sql]
        self.description = [(column,) for column in columns]
        self.rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class MetadataConnection:
    def __init__(
        self,
        responses: dict[str, tuple[list[str], list[tuple[Any, ...]]]],
    ) -> None:
        self.responses = responses
        self.executed_sql: list[str] = []
        self.closed = False

    def cursor(self) -> MetadataCursor:
        return MetadataCursor(
            responses=self.responses,
            executed_sql=self.executed_sql,
        )

    def close(self) -> None:
        self.closed = True


def make_settings() -> Settings:
    return Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars")


@pytest.mark.asyncio
async def test_trino_client_reuses_connection_between_queries() -> None:
    connections: list[FakeConnection] = []
    connect_kwargs: list[dict[str, Any]] = []

    def connect_factory(**kwargs: Any) -> FakeConnection:
        connect_kwargs.append(kwargs)
        connection = FakeConnection()
        connections.append(connection)
        return connection

    client = DbApiTrinoClient(
        settings=make_settings(),
        connect_factory=connect_factory,
    )

    first_result = await client.execute("SELECT 1")
    second_result = await client.execute("SELECT 2")

    assert first_result == [{"value": 1}]
    assert second_result == [{"value": 2}]
    assert len(connections) == 1
    assert connect_kwargs == [
        {
            "host": "localhost",
            "port": 8080,
            "user": "data-api",
            "http_scheme": "http",
        },
    ]
    assert connections[0].closed is False
    assert [cursor.executed_sql for cursor in connections[0].cursors] == [
        ["SELECT 1"],
        ["SELECT 2"],
    ]
    assert all(cursor.closed for cursor in connections[0].cursors)

    await client.close()

    assert connections[0].closed is True


@pytest.mark.asyncio
async def test_trino_client_reconnects_after_query_failure() -> None:
    class FailingCursor(FakeCursor):
        def execute(self, sql: str) -> None:
            raise RuntimeError("query failed")

    class FailingConnection(FakeConnection):
        def cursor(self) -> FakeCursor:
            cursor = FailingCursor(rows=[])
            self.cursors.append(cursor)
            return cursor

    connections: list[FakeConnection] = []
    connect_calls = 0

    def connect_factory(**kwargs: Any) -> FakeConnection:
        nonlocal connect_calls
        connect_calls += 1
        connection: FakeConnection
        if connect_calls == 1:
            connection = FailingConnection()
        else:
            connection = FakeConnection()
        connections.append(connection)
        return connection

    client = DbApiTrinoClient(
        settings=make_settings(),
        connect_factory=connect_factory,
    )

    with pytest.raises(RuntimeError, match="query failed"):
        await client.execute("SELECT broken")

    assert connections[0].closed is True

    result = await client.execute("SELECT 1")

    assert result == [{"value": 1}]
    assert len(connections) == 2


@pytest.mark.asyncio
async def test_trino_client_reads_catalog_schema_table_and_column_metadata() -> None:
    connection = MetadataConnection(
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

    def connect_factory(**kwargs: Any) -> MetadataConnection:
        return connection

    client = DbApiTrinoClient(
        settings=make_settings(),
        connect_factory=connect_factory,
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
    assert connection.executed_sql == [
        "SHOW CATALOGS",
        'SHOW SCHEMAS FROM "hive"',
        'SHOW TABLES FROM "hive"."default"',
        'SHOW COLUMNS FROM "hive"."default"."users"',
    ]
