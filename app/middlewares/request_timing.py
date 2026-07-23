import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log the total time spent processing each HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        started_at = time.perf_counter()
        status_code = 500
        log_level = logging.ERROR

        try:
            response = await call_next(request)
            status_code = response.status_code
            log_level = logging.INFO if status_code < 500 else logging.ERROR
            return response
        finally:
            logger.log(
                log_level,
                "api_request_completed method=%s path=%s status_code=%d "
                "duration_ms=%.3f",
                request.method,
                _route_path(request),
                status_code,
                (time.perf_counter() - started_at) * 1000,
            )


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"
