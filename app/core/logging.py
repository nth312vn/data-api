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
        request_id = request_id_context.get()
        if request_id:
            record.request_id = request_id
        return True


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        self.with_request_id = logging.Formatter(
            fmt=(
                "%(asctime)s %(levelname)s [%(name)s] "
                "request_id=%(request_id)s %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.without_request_id = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            record.request_id = request_id
            return self.with_request_id.format(record)
        return self.without_request_id.format(record)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = request_id_context.get()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if request_id:
            payload["request_id"] = request_id
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
