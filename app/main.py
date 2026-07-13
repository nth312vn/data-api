from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
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
    get_pii_mapping_cache,
    initialize_pii_mapping_cache,
)
from app.middlewares.request_id import RequestIDMiddleware
from app.middlewares.timeout import RequestTimeoutMiddleware
from app.services.pii_cache_sync import run_pii_cache_sync_loop

API_REQUEST_TIMEOUT_SECONDS = 120.0

# Resolve settings 1 lần duy nhất ở module-level.
# lru_cache đảm bảo mọi nơi khác gọi get_settings() đều trả cùng instance.
settings = get_settings()

# Module-level reference so the main process can manage it.
_metrics_server: MetricsServer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = get_logger(__name__)
    logger.info("application_starting")
    loaded, cached = await initialize_pii_mapping_cache(settings)
    logger.info(
        "pii_mapping_cache_initialized loaded=%d cached=%d batch_size=%d",
        loaded,
        cached,
        settings.pii_mapping_snapshot_batch_size,
    )

    # Start the background incremental sync loop.
    cache = get_pii_mapping_cache(settings)
    stop_event = asyncio.Event()
    sync_task = asyncio.create_task(
        run_pii_cache_sync_loop(
            cache=cache,
            settings=settings,
            stop_event=stop_event,
        ),
        name="pii_cache_sync",
    )

    try:
        yield
    finally:
        stop_event.set()
        await sync_task
        await close_trino_client()
        logger.info("application_stopping")


def create_app(app_settings: Settings = settings) -> FastAPI:
    configure_logging(
        app_settings.log_level,
        log_format=app_settings.log_format,
        log_file_path=app_settings.log_file_path,
        log_file_max_mb=app_settings.log_file_max_mb,
        log_file_backup_count=app_settings.log_file_backup_count,
    )

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
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
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=app_settings.api_v1_prefix)

    return app


# Guard: khi chạy `python -m app.main`, module load với tên `__main__`.
# Uvicorn sẽ re-import module với tên `app.main` và gọi create_app() lúc đó.
# Nếu không guard, create_app()/configure_logging() sẽ chạy 2 lần.
if __name__ != "__main__":
    app = create_app()


if __name__ == "__main__":
    import uvicorn

    configure_logging(
        settings.log_level,
        log_format=settings.log_format,
        log_file_path=settings.log_file_path,
        log_file_max_mb=settings.log_file_max_mb,
        log_file_backup_count=settings.log_file_backup_count,
    )
    logger = get_logger(__name__)

    # Start the Prometheus metrics server once in the main process,
    # before uvicorn forks workers. This guarantees a single metrics
    # HTTP server regardless of how many workers are spawned.
    if settings.metrics_enabled:
        _metrics_server = start_metrics_server(
            host=settings.metrics_host,
            port=settings.metrics_port,
        )
        logger.info(
            "prometheus_metrics_server_started host=%s port=%d",
            settings.metrics_host,
            settings.metrics_port,
        )

    try:
        uvicorn.run(
            "app.main:app",
            host=settings.uvicorn_host,
            port=settings.uvicorn_port,
            workers=settings.uvicorn_workers,
            log_level=settings.log_level.lower(),
        )
    finally:
        stop_metrics_server(_metrics_server)
