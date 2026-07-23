from threading import Thread
from typing import Any

from prometheus_client import start_http_server
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from starlette.applications import Starlette

from app.middlewares.request_timing import log_request_timing

# Create the metric collectors once and reuse the instrumentation callback for every
# app instance. This keeps repeated create_app() calls safe in the same process.
DEFAULT_HTTP_METRICS = metrics.default(metric_namespace="data_api")


def instrument_app(app: Starlette) -> None:
    """Add Prometheus HTTP metrics and per-request timing logs to an app."""

    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics"],
    ).add(
        DEFAULT_HTTP_METRICS,
        log_request_timing,
    ).instrument(app)


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
