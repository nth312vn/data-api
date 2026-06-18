from app.repositories.interfaces.pii_mapping import PiiMappingSnapshotRepository
from app.services.pii_mapping_cache import InMemoryPiiMappingCache


async def load_pii_mapping_snapshot(
    *,
    repository: PiiMappingSnapshotRepository,
    cache: InMemoryPiiMappingCache,
    batch_size: int,
) -> int:
    """Replace the in-memory mapping snapshot using bounded DB queries."""
    cache.clear()
    loaded = 0
    async for batch in repository.iter_snapshot_batches(
        batch_size=batch_size,
    ):
        values = {key: record.mapped_value for key, record in batch.items()}
        cache.set_many(values)
        loaded += len(values)
    return loaded
