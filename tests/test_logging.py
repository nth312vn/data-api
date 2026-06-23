import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.logging import configure_logging


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
