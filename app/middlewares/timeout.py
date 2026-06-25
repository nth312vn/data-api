import asyncio

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.exceptions import error_response
from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        timeout_seconds: float,
        excluded_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.timeout_seconds = timeout_seconds
        self.excluded_paths = excluded_paths or set()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        try:
            return await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "request_timeout method=%s path=%s timeout_seconds=%.3f",
                request.method,
                request.url.path,
                self.timeout_seconds,
            )
            return error_response(
                request=request,
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                code="request_timeout",
                message="Request timed out",
                details={"timeout_seconds": self.timeout_seconds},
            )
