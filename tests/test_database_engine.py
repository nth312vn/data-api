from typing import Any

import pytest

from app.infrastructure.database import engine as engine_module


def test_create_postgres_async_engine_applies_pool_and_timeout_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_engine = object()

    def fake_create_async_engine(*args: Any, **kwargs: Any) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_engine

    monkeypatch.setattr(
        engine_module,
        "create_async_engine",
        fake_create_async_engine,
    )

    result = engine_module.create_postgres_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/data_api",
        pool_size=7,
        max_overflow=9,
        pool_timeout_seconds=11.0,
        pool_recycle_seconds=1200,
        connect_timeout_seconds=3.5,
        statement_timeout_seconds=12.25,
    )

    assert result is fake_engine
    assert captured["args"] == (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/data_api",
    )
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 9,
        "pool_timeout": 11.0,
        "pool_recycle": 1200,
        "pool_use_lifo": True,
        "connect_args": {
            "timeout": 3.5,
            "command_timeout": 12.25,
            "server_settings": {
                "statement_timeout": "12250",
            },
        },
    }
