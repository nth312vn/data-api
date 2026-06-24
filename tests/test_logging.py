import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.logging import configure_logging


def test_default_log_file_path_uses_writable_container_path() -> None:
    settings = Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars")

    assert settings.log_file_path == "/var/log/data-api/data-api.log"


def test_configure_logging_writes_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"

    try:
        configure_logging("INFO", log_file_path=str(log_file), log_file_max_mb=1)
        logger = logging.getLogger("tests.file_logging")
        logger.info("file log message")

        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_file.exists()
        assert "file log message" in log_file.read_text(encoding="utf-8")
        file_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        assert file_handlers[0].maxBytes == 1024 * 1024
    finally:
        configure_logging("INFO", log_file_path=None)


def test_configure_logging_falls_back_when_file_path_is_not_writable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_permission_error(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "mkdir", raise_permission_error)

    try:
        configure_logging("INFO", log_file_path="logs/data-api.log")
        file_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, RotatingFileHandler)
        ]

        assert file_handlers == []
    finally:
        configure_logging("INFO", log_file_path=None)
