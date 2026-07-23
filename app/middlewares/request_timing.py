import logging

from prometheus_fastapi_instrumentator.metrics import Info

from app.core.logging import get_logger

logger = get_logger(__name__)


def log_request_timing(info: Info) -> None:
    """Log request timing measured by Prometheus Instrumentator."""

    status_code = info.response.status_code if info.response is not None else 500
    log_level = logging.INFO if status_code < 500 else logging.ERROR
    logger.log(
        log_level,
        "api_request_completed method=%s path=%s status_code=%d "
        "duration_ms=%.3f",
        info.method,
        info.modified_handler,
        status_code,
        info.modified_duration * 1000,
    )
