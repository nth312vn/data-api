from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_postgres_async_engine(
    url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout_seconds: float,
    pool_recycle_seconds: int,
    connect_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
        pool_recycle=pool_recycle_seconds,
        pool_use_lifo=True,
        connect_args=_asyncpg_connect_args(
            connect_timeout_seconds=connect_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
        ),
    )


def _asyncpg_connect_args(
    *,
    connect_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> dict[str, Any]:
    statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))
    return {
        "timeout": connect_timeout_seconds,
        "command_timeout": statement_timeout_seconds,
        "server_settings": {
            "statement_timeout": str(statement_timeout_ms),
        },
    }
