import asyncio

from app.core.config import Settings
from app.core.logging import get_logger
from app.infrastructure.pii_database.session import PiiAsyncSessionFactory
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.services.pii_mapping_snapshot import (
    load_pii_mapping_incremental,
    load_pii_mapping_snapshot,
)

logger = get_logger(__name__)


async def run_pii_cache_sync_loop(
    *,
    cache: InMemoryPiiMappingCache,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Background loop that keeps the PII mapping cache up to date.

    Each iteration:
    1. If cache.last_synced_at is None (init failed or never ran), run a full
       snapshot to recover. This handles the case where startup init errored out
       and left the cache uninitialized.
    2. Otherwise run an incremental sync to upsert records newer than
       last_synced_at.
    3. Sleep for pii_sync_interval_seconds, then repeat.

    The loop runs until stop_event is set. All exceptions are caught and logged
    so a transient DB error never kills the loop.
    """
    interval = settings.pii_sync_interval_seconds
    batch_size = settings.pii_mapping_snapshot_batch_size
    logger.info("pii_cache_sync_loop_started interval_seconds=%.1f", interval)

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval,
            )
            # stop_event fired during sleep → exit cleanly
            break
        except asyncio.TimeoutError:
            pass  # normal: interval elapsed, proceed to sync

        try:
            async with PiiAsyncSessionFactory() as session:
                repository = SQLAlchemyPiiMappingRepository(
                    session=session,
                    query_batch_size=batch_size,
                )

                if cache.last_synced_at is None:
                    # Cache was never initialized (startup failed) — do full snapshot
                    logger.warning(
                        "pii_cache_sync_recovery_snapshot "
                        "reason=last_synced_at_is_none"
                    )
                    loaded = await load_pii_mapping_snapshot(
                        repository=repository,
                        cache=cache,
                        batch_size=batch_size,
                    )
                    logger.info(
                        "pii_cache_sync_recovery_snapshot_done "
                        "loaded=%d cached=%d",
                        loaded,
                        cache.size,
                    )
                else:
                    loaded = await load_pii_mapping_incremental(
                        repository=repository,
                        cache=cache,
                        batch_size=batch_size,
                    )
                    if loaded:
                        logger.info(
                            "pii_cache_sync_incremental_done "
                            "loaded=%d cached=%d last_synced_at=%s",
                            loaded,
                            cache.size,
                            cache.last_synced_at,
                        )

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "pii_cache_sync_error error=%s",
                exc,
            )

    logger.info("pii_cache_sync_loop_stopped")
