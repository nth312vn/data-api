from app.repositories.interfaces.pii_mapping import PiiMappingSnapshotRepository
from app.services.account_map_in_memory import AccountMapInMemory


async def load_pii_mapping_snapshot(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: AccountMapInMemory,
    batch_size: int,
) -> int:
    """Replace the in-memory mapping snapshot using bounded DB queries.

    Clears the cache before loading so stale entries are removed.
    Updates cache.last_synced_at with the max created_at seen across all records.
    """
    cache.clear()

    loaded = 0
    offset = 0
    while True:
        records = await repository.get_mappings_batch(
            limit=batch_size,
            offset=offset,
        )
        if not records:
            break

        cache.add_records(records)
        loaded += len(records)
        offset += batch_size

    return loaded


async def load_pii_mapping_incremental(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: AccountMapInMemory,
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
    offset = 0
    while True:
        records = await repository.get_mappings_batch(
            since=since,
            limit=batch_size,
            offset=offset,
        )
        if not records:
            break

        cache.add_records(records)
        loaded += len(records)
        offset += batch_size

    return loaded
