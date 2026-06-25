from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    MetricsServer,
    PrometheusMiddleware,
    start_metrics_server,
    stop_metrics_server,
)
from app.dependencies.services import (
    close_trino_client,
    initialize_pii_mapping_cache,
)
from app.middlewares.request_id import RequestIDMiddleware
from app.middlewares.timeout import RequestTimeoutMiddleware

API_REQUEST_TIMEOUT_SECONDS = 120.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = get_logger(__name__)
    logger.info("application_starting")
    settings = get_settings()
    metrics_server: MetricsServer | None = None
    if settings.metrics_enabled:
        metrics_server = start_metrics_server(
            host=settings.metrics_host,
            port=settings.metrics_port,
        )
        logger.info(
            "prometheus_metrics_server_started host=%s port=%d",
            settings.metrics_host,
            settings.metrics_port,
        )
    loaded, cached = await initialize_pii_mapping_cache(settings)
    logger.info(
        "pii_mapping_cache_initialized loaded=%d cached=%d batch_size=%d",
        loaded,
        cached,
        settings.pii_mapping_snapshot_batch_size,
    )
    try:
        yield
    finally:
        stop_metrics_server(metrics_server)
        await close_trino_client()
        logger.info("application_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        log_format=settings.log_format,
        log_file_path=settings.log_file_path,
        log_file_max_mb=settings.log_file_max_mb,
        log_file_backup_count=settings.log_file_backup_count,
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        RequestTimeoutMiddleware,
        timeout_seconds=API_REQUEST_TIMEOUT_SECONDS,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
