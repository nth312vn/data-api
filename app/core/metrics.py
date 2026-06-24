import time
from threading import Thread
from typing import Any

from prometheus_client import Counter, Histogram, start_http_server
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

REQUEST_COUNT = Counter(
    "data_api_http_requests_total",
    "Total HTTP requests.",
    ("method", "path", "status_code"),
)
REQUEST_DURATION = Histogram(
    "data_api_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "path"),
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        excluded_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.excluded_paths = excluded_paths or {"/metrics"}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        start_time = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            path = self._route_path(request)
            duration = time.perf_counter() - start_time
            REQUEST_COUNT.labels(
                method=request.method,
                path=path,
                status_code=str(status_code),
            ).inc()
            REQUEST_DURATION.labels(
                method=request.method,
                path=path,
            ).observe(duration)

    @staticmethod
    def _route_path(request: Request) -> str:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        if isinstance(path, str):
            return path

        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match is Match.FULL:
                path = getattr(route, "path", None)
                if isinstance(path, str):
                    return path

        return request.url.path


MetricsServer = tuple[Any, Thread]


def start_metrics_server(*, host: str, port: int) -> MetricsServer:
    server, thread = start_http_server(port, addr=host)
    return server, thread


def stop_metrics_server(metrics_server: MetricsServer | None) -> None:
    if metrics_server is None:
        return
    server, thread = metrics_server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
