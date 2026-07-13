from app.repositories.interfaces.pii_mapping import PiiMappingSnapshotRepository
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


async def load_pii_mapping_snapshot(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: InMemoryPiiMappingCache,
) -> int:
    """Replace the in-memory mapping snapshot using bounded DB queries.

    Clears the cache before loading so stale entries are removed.
    Updates cache.last_synced_at with the max created_at seen across all records.
    """
    cache.clear()
    records = await repository.fetch_all_mappings()
    if records:
        cache.set_many(records)
    return len(records)


async def load_pii_mapping_incremental(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: InMemoryPiiMappingCache,
) -> int:
    """Upsert records newer than cache.last_synced_at into cache without clearing.

    Returns 0 immediately if last_synced_at is None (cache not initialized).
    The caller should run a full snapshot first in that case.
    """
    since = cache.last_synced_at
    if since is None:
        return 0

    records = await repository.fetch_all_mappings(since=since)
    if records:
        cache.set_many(records)
    return len(records)
