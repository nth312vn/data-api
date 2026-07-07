from app.repositories.interfaces.pii_mapping import PiiMappingSnapshotRepository
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


async def load_pii_mapping_snapshot(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: InMemoryPiiMappingCache,
    batch_size: int,
) -> int:
    """Replace the in-memory mapping snapshot using bounded DB queries.

    Clears the cache before loading so stale entries are removed.
    Updates cache.last_synced_at with the max created_at seen across all batches.
    """
    cache.clear()
    loaded = 0
    async for batch in repository.iter_snapshot_batches(
        batch_size=batch_size,
    ):
        values = {key: record.mapped_value for key, record in batch.items()}
        cache.set_many(values)
        loaded += len(values)
        # Track the newest created_at seen so incremental sync can resume from here
        for record in batch.values():
            if record.created_at is not None:
                cache.update_last_synced_at(record.created_at)
    return loaded


async def load_pii_mapping_incremental(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: InMemoryPiiMappingCache,
    batch_size: int,
) -> int:
    """Upsert records newer than cache.last_synced_at into cache without clearing.

    Returns 0 immediately if last_synced_at is None (cache not initialized).
    The caller should run a full snapshot first in that case.
    """
    since = cache.last_synced_at
    if since is None:
        return 0

    loaded = 0
    async for batch in repository.iter_incremental_batches(
        since=since,
        batch_size=batch_size,
    ):
        values = {key: record.mapped_value for key, record in batch.items()}
        cache.set_many(values)
        loaded += len(values)
        for record in batch.values():
            if record.created_at is not None:
                cache.update_last_synced_at(record.created_at)
    return loaded
