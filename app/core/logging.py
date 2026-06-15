import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get() or "-"
        return True


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt=(
                "%(asctime)s %(levelname)s [%(name)s] "
                "request_id=%(request_id)s %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get() or None,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value),
                "traceback": [
                    line
                    for entry in traceback.format_exception(
                        exc_type,
                        exc_value,
                        exc_traceback,
                    )
                    for line in entry.rstrip().splitlines()
                ],
            }
        return json.dumps(
            payload,
            default=str,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def configure_logging(level: str, *, log_format: str = "text") -> None:
    level_name = level.upper()
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level_name)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(level_name)
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
